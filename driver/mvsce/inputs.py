"""External inputs: read inputs.lock, fetch into the cache, verify, extract.

A file is used only after its size and SHA-256 (and, where the lock has
one, the publisher's md5) match the lock. A mismatch stops the build: for
Jay Moseley's objects it means he has published new files under the same
URL, which needs a new label, not a retry.
"""
import hashlib
import shutil
import tarfile
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .log import BuildError, info


@dataclass(frozen=True)
class Input:
    label: str
    name: str
    url: str
    size: int
    sha256: str
    md5: str = ''
    into: str = ''      # subdirectory of the build tree to extract into


def load_lock(path):
    with open(path, 'rb') as f:
        data = tomllib.load(f)
    return [Input(**entry) for entry in data.get('input', [])]


def load_config(path):
    with open(path, 'rb') as f:
        return tomllib.load(f)


def select(inputs, label):
    chosen = [i for i in inputs if i.label == label]
    if not chosen:
        labels = sorted({i.label for i in inputs})
        raise BuildError(f"label {label!r} is not in inputs.lock "
                         f"(it has: {', '.join(labels)})")
    return chosen


def _digests(path):
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            sha.update(block)
            md5.update(block)
    return sha.hexdigest(), md5.hexdigest()


def _mismatch(item, path):
    size = path.stat().st_size
    sha, md5 = _digests(path)
    problems = []
    if size != item.size:
        problems.append(f'size {size}, lock says {item.size}')
    if sha != item.sha256:
        problems.append(f'sha256 {sha}, lock says {item.sha256}')
    if item.md5 and md5 != item.md5:
        problems.append(f'md5 {md5}, lock says {item.md5}')
    return problems


def fetch(item, cache_dir):
    """Return the verified cached copy of item, downloading it if needed."""
    target = Path(cache_dir) / 'inputs' / item.sha256 / item.name
    if target.exists() and not _mismatch(item, target):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + '.part')
    info(f'fetching {item.name} ({item.label}) from {item.url}')
    request = urllib.request.Request(item.url, headers={'User-Agent': 'mvsce-build'})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, \
                open(partial, 'wb') as out:
            shutil.copyfileobj(response, out)
    except OSError as e:
        partial.unlink(missing_ok=True)
        raise BuildError(f'download of {item.url} failed: {e}') from e
    problems = _mismatch(item, partial)
    if problems:
        kept = partial.with_suffix('.mismatch')
        partial.replace(kept)
        raise BuildError(
            f'{item.name} from {item.url} does not match inputs.lock '
            f'({"; ".join(problems)}). The publisher has changed the file: '
            f'add it to inputs.lock under a new label instead of editing '
            f'{item.label!r}. The download is kept as {kept}.')
    partial.replace(target)
    return target


def extract(archive, dest):
    """Extract a .tar.gz into dest; refuses links and paths leaving dest."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:gz') as tar:
        tar.extractall(dest, filter='data')
