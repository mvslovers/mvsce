"""DASD images: create them with dasdinit, read their VTOC with dasdls."""
import re
import subprocess
from pathlib import Path

from .log import BuildError


def create(path, devtype, volser, compress=False):
    """Create an empty volume (dasdinit -a: the full size, as Jay does)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    args = ['dasdinit', '-a'] + (['-z'] if compress else []) + [str(path), devtype, volser]
    r = subprocess.run(args, capture_output=True, text=True, errors='replace')
    if r.returncode != 0 or not path.exists():
        raise BuildError(f'{" ".join(args)} failed (rc {r.returncode}):\n{r.stdout}{r.stderr}')


def vtoc(path):
    """Return (volser, set of data set names) of a volume."""
    r = subprocess.run(['dasdls', str(path)], capture_output=True, text=True,
                       errors='replace')
    out = r.stdout + r.stderr
    m = re.search(r'VOLSER:\s+(\S+)', out)
    if r.returncode != 0 or not m:
        raise BuildError(f'dasdls {path} failed (rc {r.returncode}):\n{out}')
    names = set()
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith(('VOLSER:', 'End of dasdls', 'HHC')):
            continue
        names.add(line.split()[0])
    return m.group(1), names


def check(path, volser, datasets):
    """Raise unless the volume has volser and every data set in datasets."""
    found_volser, names = vtoc(path)
    problems = []
    if found_volser != volser:
        problems.append(f'volser is {found_volser}, expected {volser}')
    missing = sorted(set(datasets) - names)
    if missing:
        problems.append('missing: ' + ', '.join(missing))
    if problems:
        raise BuildError(f'{path}: ' + '; '.join(problems))
    return names
