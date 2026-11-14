"""Stage runner and stage cache.

The build tree (build/jay/) is Jay Moseley's directory layout: his
installation objects and tapes extracted into one directory, dasd/ beside
them. Hercules runs there with Jay's configuration files, so the paths in
them hold unchanged.

Each stage's result is the content of dasd/ and conf/ (Jay changes his
Hercules configuration along the way, S4 does it with him). It is cached
under a key
that covers everything the result depends on: the stage's source, the
driver, the selected inputs, the Hercules version and the previous
stage's key. A stage whose key is cached is restored instead of run.
"""
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from . import dasd, hercules, inputs, mvs
from .log import BuildError, info
from .stages import STAGES

DRIVER = Path(__file__).resolve().parent

# What a stage leaves behind for the next: the volumes and the Hercules
# configuration.
STATE = ('dasd', 'conf')


class Context:
    def __init__(self, root, work, cache, hercules_bin):
        self.root = Path(root)
        self.work = Path(work)
        self.tree = self.work / 'jay'
        self.logs = self.work / 'logs'
        self.cache = Path(cache)
        self.hercules_bin = hercules_bin
        self.dasd = dasd
        self.stage = None

    def hercules(self, config):
        log = self.logs / f'{self.stage}.log'
        return hercules.Hercules(config, self.tree, log, binary=self.hercules_bin,
                                 on_exit=self._keep_printers)

    def _keep_printers(self):
        """Every Hercules session's printer files go to logs/, also when the
        session failed: the next session would overwrite them (issue #7
        lost its evidence that way)."""
        for prt in sorted(self.tree.glob('prt*.txt')):
            n = 1
            while (target := self.logs / f'{self.stage}-{n}-{prt.name}').exists():
                n += 1
            shutil.copy(prt, target)


def _driver_digest(root):
    """The driver and our own jobs (jcl/): both shape every stage result."""
    h = hashlib.sha256()
    files = sorted(DRIVER.rglob('*.py')) + sorted((Path(root) / 'jcl').glob('*'))
    for path in files:
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def _patches(root, label):
    return sorted((Path(root) / 'patches' / label).glob('*.patch'))


def _apply_patches(ctx, patches):
    """Our changes to Jay's files, kept per label; each must apply cleanly."""
    for patch in patches:
        r = subprocess.run(['patch', '-p1', '--forward', '--batch', '-i', str(patch)],
                           cwd=ctx.tree, capture_output=True, text=True)
        if r.returncode != 0:
            raise BuildError(f'{patch.name} does not apply to this version of '
                             f"Jay's objects:\n{r.stdout}{r.stderr}")
        info(f'patched: {patch.name}')


def prepare(ctx, selected, patches=()):
    """Fetch and verify the inputs, extract them into a fresh tree, patch it."""
    if ctx.tree.exists():
        shutil.rmtree(ctx.tree)
    ctx.tree.mkdir(parents=True)
    if ctx.logs.exists():
        shutil.rmtree(ctx.logs)      # one build, one set of logs
    ctx.logs.mkdir(parents=True)
    for item in selected:
        archive = inputs.fetch(item, ctx.cache)
        inputs.extract(archive, ctx.tree / item.into)
    _check_md5sums(ctx.tree / 'tape')
    _apply_patches(ctx, patches)
    (ctx.tree / 'dasd').mkdir(exist_ok=True)


def _check_md5sums(tape_dir):
    """Jay ships md5 lists for his tapes; hold every tape to them."""
    lists = sorted(tape_dir.glob('*.md5sums'))
    if not lists:
        raise BuildError(f'no *.md5sums in {tape_dir}')
    for lst in lists:
        for line in lst.read_text().splitlines():
            if not line.strip():
                continue
            digest, name = line.split()
            got = hashlib.md5((tape_dir / name).read_bytes()).hexdigest()
            if got != digest:
                raise BuildError(f'{tape_dir / name}: md5 {got}, {lst.name} says {digest}')


def _save(ctx, stage, key):
    target = ctx.cache / 'stages' / f'{stage.NAME}-{key[:16]}'
    partial = target.with_name(target.name + '.part')
    if partial.exists():
        shutil.rmtree(partial)
    for part in STATE:
        shutil.copytree(ctx.tree / part, partial / part)
    (partial / 'stage.json').write_text(json.dumps(
        {'stage': stage.NAME, 'key': key, 'saved': time.strftime('%Y-%m-%dT%H:%M:%S')},
        indent=2) + '\n')
    if target.exists():
        shutil.rmtree(target)
    partial.rename(target)
    (ctx.cache / 'stages' / f'{stage.NAME}.latest').write_text(target.name + '\n')
    _prune(ctx, stage, keep=2)


def _prune(ctx, stage, keep):
    """Keep the newest results of a stage; each is a full set of DASD."""
    results = sorted((d for d in (ctx.cache / 'stages').glob(f'{stage.NAME}-*')
                      if d.is_dir() and not d.name.endswith('.part')),
                     key=lambda d: d.stat().st_mtime, reverse=True)
    for old in results[keep:]:
        shutil.rmtree(old)


def _restore_latest(ctx, stage):
    """The last verified result of stage, whatever its key (--from)."""
    pointer = ctx.cache / 'stages' / f'{stage.NAME}.latest'
    if not pointer.exists():
        raise BuildError(f'--from needs a cached result of {stage.NAME}; build it first')
    source = ctx.cache / 'stages' / pointer.read_text().strip()
    _copy_state(source, ctx.tree)
    return source.name


def _restore(ctx, stage, key):
    source = ctx.cache / 'stages' / f'{stage.NAME}-{key[:16]}'
    if not (source / 'stage.json').exists():
        return False
    if json.loads((source / 'stage.json').read_text()).get('key') != key:
        return False
    _copy_state(source, ctx.tree)
    return True


def _copy_state(source, tree):
    for part in STATE:
        if not (source / part).is_dir():
            raise BuildError(f'{source} has no {part}/; it predates conf/ in stage '
                             f'results: rebuild the stage before it')
        shutil.rmtree(tree / part)
        shutil.copytree(source / part, tree / part)


def build(root, work, cache, until=None, start=None, use_cache=True,
          hercules_bin='hercules', record=False):
    """Run the stages up to until.

    start: begin at this stage, on the last verified result of the stage
    before it, whatever that was built from. For working on a stage; the
    results are not cached, because their inputs are no longer known.
    """
    root = Path(root)
    config = inputs.load_config(root / 'config' / 'sysgen.toml')
    label = config['jay']['label']
    lock = inputs.load_lock(root / 'inputs.lock')
    selected = inputs.select(lock, label) + inputs.select(lock, config['syscpk']['label'])
    herc_version = hercules.version(hercules_bin)
    info(f'Jay Moseley objects: {label}; SYSCPK: {config["syscpk"]["label"]}; '
         f'{herc_version}')

    stages = STAGES
    if until:
        names = [s.NAME for s in STAGES]
        if until not in names:
            raise BuildError(f'unknown stage {until!r} (stages: {", ".join(names)})')
        stages = STAGES[:names.index(until) + 1]

    names = [s.NAME for s in STAGES]
    if start:
        if start not in names:
            raise BuildError(f'unknown stage {start!r} (stages: {", ".join(names)})')
        first = names.index(start)
        stages = [s for s in stages if names.index(s.NAME) >= first]
        if not stages:
            raise BuildError(f'--from {start} is after --until {until}')

    patches = _patches(root, label)
    ctx = Context(root, work, cache, hercules_bin)
    prepare(ctx, selected, patches)

    key = hashlib.sha256('\n'.join(
        [label, herc_version, _driver_digest(root)] + [i.sha256 for i in selected]
        + [hashlib.sha256(p.read_bytes()).hexdigest() for p in patches]
    ).encode()).hexdigest()

    if start and names.index(start) > 0:
        before = STAGES[names.index(start) - 1]
        info(f'--from {start}: using the last result of {before.NAME} '
             f'({_restore_latest(ctx, before)}); nothing will be cached')
        use_cache = False

    if record:
        mvs.record = []
        use_cache = False
        info('--record: condition codes are recorded, not enforced; nothing is cached')

    for stage in stages:
        key = hashlib.sha256(f'{key}\n{stage.NAME}'.encode()).hexdigest()
        ctx.stage = stage.NAME
        if use_cache and _restore(ctx, stage, key):
            info(f'{stage.NAME} {stage.TITLE}: restored from cache ({key[:16]})')
            stage.verify(ctx)
            continue
        info(f'{stage.NAME} {stage.TITLE}: running')
        started = time.monotonic()
        stage.run(ctx)
        stage.verify(ctx)
        info(f'{stage.NAME} {stage.TITLE}: verified, '
             f'{time.monotonic() - started:.0f}s')
        if use_cache:
            _save(ctx, stage, key)
    if record and mvs.record:
        raise BuildError('--record: condition codes differing from the expectation:\n  '
                         + '\n  '.join(mvs.record))
    info(f'done: {", ".join(s.NAME for s in stages)}; DASD in {ctx.tree / "dasd"}')
