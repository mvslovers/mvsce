"""The release package: the finished system, ready to run under Hercules.

    dist/mvsce-<version>/
        conf/mvs.cnf        Jay Moseley's configuration, as the build left it
        dasd/               the volumes conf/mvs.cnf attaches, as compressed
                            CCKD (dasdcopy -z); Hercules reads them as they are
        start_mvs.sh        starts Hercules with conf/mvs.cnf
        README.md           how to IPL and shut down (Jay's procedure)
        MANIFEST.json       versions, inputs, patches, SMP inventory summary,
                            and size and SHA-256 of every file
        smp-inventory.txt   every SYSMOD of the target zone with its status
    dist/mvsce-<version>.tar, .tar.sha256

The package is made from the build tree of a complete build (S1-S5). It is
then started once from a copy: a normal IPL until TSO accepts logons, and
Jay's shutdown. What is shipped is what was booted.
"""
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

from . import dasd, hercules, inputs, smp
from .log import BuildError, info
from .mvs import Console

START_SCRIPT = '''#!/bin/sh
# Start MVS/CE: Hercules with Jay Moseley's configuration. See README.md.
cd "$(dirname "$0")" || exit 1
exec hercules -f conf/mvs.cnf "$@"
'''

README = '''# MVS/CE {version}

MVS 3.8j as built by Jay Moseley's installation procedure ({jay}),
automated by https://github.com/mvslovers/mvsce. MANIFEST.json lists what
went into it.

## Start

Needs Hercules (SDL Hyperion; this package was booted with
{hercules}). From this directory:

    ./start_mvs.sh

Connect a 3270 client to localhost port 3270 for the master console
(device 010) and TSO (devices 400-407). The integrated console 009 is the
Hercules console itself: commands for MVS start with `/`.

At the Hercules prompt:

    ipl 150

and answer, on the master console or with `/` on the Hercules console
(`nn` is the reply id the message shows, usually 00 and 01):

| Message  | Reply                     |
|----------|---------------------------|
| IEA101A  | Enter (`/` alone)         |
| IFB010D  | `r nn,u`                  |
| $HASP426 | `r nn,noreq` (warm start) |

Then start VTAM and TSO with `s net`; TSO accepts logons when IKT007I
appears. Jay's TSO users HMVS01 and HMVS02 log on without a password.
Jobs can be sent to the card reader at 00C, a socket on localhost port
3505 (ASCII), for example with `nc localhost 3505 < job.jcl`.

## Shut down

    p tso
    z net,quick
    $p jes2
    z eod
    quiesce

then `quit` at the Hercules prompt.

## Volumes

| Address | Volume | Device | Use |
|---------|--------|--------|-----|
{volumes}
'''

USES = {
    'MVSRES': 'system residence',
    'MVS000': 'system data sets, JES2 checkpoint',
    'PAGE00': 'page data sets',
    'SPOOL1': 'JES2 spool',
    'PUB000': 'TSO users, RPF',
    'PUB001': 'user catalogs, VSAM space',
    'SMP000': 'distribution libraries, SMP data sets',
    'WORK00': 'work volume',
    'WORK01': 'work volume',
    'SYSCPK': 'compilers and tools',
}

DEVICE = re.compile(r'^([0-9A-F]{4})\s+(\d{4})\s+(dasd/\S+)', re.M)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _git_commit(root):
    r = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True)
    commit = r.stdout.strip() if r.returncode == 0 else 'unknown'
    r = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=root,
                       capture_output=True, text=True)
    return commit + ('-modified' if r.stdout.strip() else '')


def _volumes(tree):
    """(address, device type, file) for every volume conf/mvs.cnf attaches."""
    found = DEVICE.findall((tree / 'conf' / 'mvs.cnf').read_text())
    if not found:
        raise BuildError('conf/mvs.cnf attaches no DASD')
    return found


def package(root, work, dist, version, hercules_bin='hercules'):
    root, work, dist = Path(root), Path(work), Path(dist)
    tree = work / 'jay'
    if not re.fullmatch(r'\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?', version):
        raise BuildError(f'version {version!r} is not MAJOR.MINOR.PATCH[-PRE]')
    listing = work / 'logs' / 'smp-s3.txt'
    if not listing.exists():
        raise BuildError(f'{listing} is missing: package after a complete build '
                         f'(./sysgen build), not after --from')

    config = inputs.load_config(root / 'config' / 'sysgen.toml')
    lock = inputs.load_lock(root / 'inputs.lock')
    used = (inputs.select(lock, config['jay']['label'])
            + inputs.select(lock, config['syscpk']['label']))
    patches = sorted((root / 'patches' / config['jay']['label']).glob('*.patch'))
    herc_version = hercules.version(hercules_bin)

    name = f'mvsce-{version}'
    out = dist / name
    if out.exists():
        shutil.rmtree(out)
    (out / 'conf').mkdir(parents=True)
    (out / 'dasd').mkdir()
    shutil.copy(tree / 'conf' / 'mvs.cnf', out / 'conf' / 'mvs.cnf')

    volumes = []
    for address, devtype, rel in _volumes(tree):
        src = tree / rel
        volser, _ = dasd.vtoc(src)
        dst = out / rel
        r = subprocess.run(['dasdcopy', '-z', str(src), str(dst)], capture_output=True,
                           text=True, errors='replace')
        if r.returncode != 0 or not dst.exists():
            raise BuildError(f'dasdcopy -z {src} failed (rc {r.returncode}):\n{r.stdout}{r.stderr}')
        volumes.append({'address': address, 'device': devtype, 'volser': volser,
                        'file': rel})
        info(f'  {address} {devtype} {volser:6} {rel}: '
             f'{src.stat().st_size >> 20} MB -> {dst.stat().st_size >> 20} MB')

    inv = smp.inventory(listing.read_text(errors='replace'))
    (out / 'smp-inventory.txt').write_text(''.join(
        f'{sysmod:8} {typ:10} {" ".join(status)}\n'
        for sysmod, (typ, status, _) in sorted(inv.items())))

    start = out / 'start_mvs.sh'
    start.write_text(START_SCRIPT)
    start.chmod(0o755)
    (out / 'README.md').write_text(README.format(
        version=version, jay=config['jay']['label'], hercules=herc_version,
        volumes='\n'.join(f'| {v["address"]} | {v["volser"]} | {v["device"]} | '
                          f'{USES.get(v["volser"], "")} |' for v in volumes)))

    manifest = {
        'product': 'MVS/CE',
        'version': version,
        'built': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source': {'repository': 'https://github.com/mvslovers/mvsce',
                   'commit': _git_commit(root)},
        'hercules': herc_version,
        'inputs': [{'label': i.label, 'name': i.name, 'url': i.url, 'sha256': i.sha256}
                   for i in used],
        'patches': [{'name': p.name, 'sha256': _sha256(p)} for p in patches],
        'smp': smp.summary(inv),
        'volumes': volumes,
    }
    _boot_test(out, hercules_bin)
    manifest['files'] = [{'path': str(p.relative_to(out)), 'size': p.stat().st_size,
                          'sha256': _sha256(p)}
                         for p in sorted(out.rglob('*')) if p.is_file()]
    (out / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')

    tar = dist / f'{name}.tar'
    with tarfile.open(tar, 'w') as t:
        t.add(out, arcname=name)
    (dist / f'{name}.tar.sha256').write_text(f'{_sha256(tar)}  {tar.name}\n')
    info(f'package: {tar} ({tar.stat().st_size >> 20} MB)')
    return tar


def _boot_test(out, hercules_bin):
    """Start the package from a copy: normal IPL, TSO up, Jay's shutdown."""
    test = out.parent / f'{out.name}.boot-test'
    if test.exists():
        shutil.rmtree(test)
    shutil.copytree(out, test)
    info('  boot test of the package')
    try:
        with hercules.Hercules('conf/mvs.cnf', test, test / 'boot-test.log',
                               binary=hercules_bin) as herc:
            herc.wait_for(r'HHC00414I 0:0253', 60, since=0, what='Hercules start')
            con = Console(herc, test, reader='localhost:3505')
            con.ipl('150', [('IEA101A', ''), ('IFB010D', 'u'), ('$HASP426', 'noreq')])
            since = herc.mark()
            con.command('s net')
            herc.wait_for(r'IKT007I', 300, since=since, what='TSO accepting logons (IKT007I)')
            con.shutdown(before=['p tso', 'z net,quick'])
        info('  boot test: IPL, TSO up (IKT007I), shutdown')
    finally:
        log = test / 'boot-test.log'
        if log.exists():
            shutil.copy(log, out.parent / f'{out.name}-boot-test.log')
        shutil.rmtree(test, ignore_errors=True)
