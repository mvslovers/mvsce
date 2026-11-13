"""Stage runner and stage cache.

The build tree (build/jay/) is Jay Moseley's directory layout: his
installation objects and tapes extracted into one directory, dasd/ beside
them. Hercules runs there with Jay's configuration files, so the paths in
them hold unchanged.

Each stage's result is the content of dasd/. It is cached under a key
that covers everything the result depends on: the stage's source, the
driver, the selected inputs, the Hercules version and the previous
stage's key. A stage whose key is cached is restored instead of run.
"""
import hashlib
import json
import shutil
import time
from pathlib import Path

from . import dasd, hercules, inputs
from .log import BuildError, info
from .stages import STAGES

DRIVER = Path(__file__).resolve().parent


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
        return hercules.Hercules(config, self.tree, log, binary=self.hercules_bin)


def _driver_digest():
    h = hashlib.sha256()
    for path in sorted(DRIVER.rglob('*.py')):
        h.update(str(path.relative_to(DRIVER)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def prepare(ctx, selected):
    """Fetch and verify the inputs, extract them into a fresh tree."""
    if ctx.tree.exists():
        shutil.rmtree(ctx.tree)
    ctx.tree.mkdir(parents=True)
    ctx.logs.mkdir(parents=True, exist_ok=True)
    for item in selected:
        archive = inputs.fetch(item, ctx.cache)
        inputs.extract(archive, ctx.tree)
    _check_md5sums(ctx.tree / 'tape')
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
    shutil.copytree(ctx.tree / 'dasd', partial / 'dasd')
    (partial / 'stage.json').write_text(json.dumps(
        {'stage': stage.NAME, 'key': key, 'saved': time.strftime('%Y-%m-%dT%H:%M:%S')},
        indent=2) + '\n')
    if target.exists():
        shutil.rmtree(target)
    partial.rename(target)


def _restore(ctx, stage, key):
    source = ctx.cache / 'stages' / f'{stage.NAME}-{key[:16]}'
    if not (source / 'stage.json').exists():
        return False
    if json.loads((source / 'stage.json').read_text()).get('key') != key:
        return False
    shutil.rmtree(ctx.tree / 'dasd')
    shutil.copytree(source / 'dasd', ctx.tree / 'dasd')
    return True


def build(root, work, cache, until=None, use_cache=True, hercules_bin='hercules'):
    root = Path(root)
    config = inputs.load_config(root / 'config' / 'sysgen.toml')
    label = config['jay']['label']
    selected = inputs.select(inputs.load_lock(root / 'inputs.lock'), label)
    herc_version = hercules.version(hercules_bin)
    info(f'Jay Moseley objects: {label}; {herc_version}')

    stages = STAGES
    if until:
        names = [s.NAME for s in STAGES]
        if until not in names:
            raise BuildError(f'unknown stage {until!r} (stages: {", ".join(names)})')
        stages = STAGES[:names.index(until) + 1]

    ctx = Context(root, work, cache, hercules_bin)
    prepare(ctx, selected)

    key = hashlib.sha256('\n'.join(
        [label, herc_version, _driver_digest()] + [i.sha256 for i in selected]
    ).encode()).hexdigest()

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
    info(f'done: {", ".join(s.NAME for s in stages)}; DASD in {ctx.tree / "dasd"}')
