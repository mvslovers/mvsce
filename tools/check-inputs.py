#!/usr/bin/env python3
"""Check every file in inputs.lock against what its URL serves now.

Downloads each file, compares size and SHA-256 with the lock and prints one
line per file. Exit code 0 when all match, 1 when one differs or cannot be
fetched. Used by the weekly workflow; Jay Moseley replaces his files under
the same URL, and a changed file needs a new label in inputs.lock.
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'driver'))
from mvsce.inputs import load_lock  # noqa: E402


def main():
    bad = []
    for item in load_lock(ROOT / 'inputs.lock'):
        req = urllib.request.Request(item.url, headers={'User-Agent': 'mvsce-build'})
        try:
            sha, size = hashlib.sha256(), 0
            with urllib.request.urlopen(req, timeout=120) as r:
                for block in iter(lambda: r.read(1 << 20), b''):
                    sha.update(block)
                    size += len(block)
        except OSError as e:
            bad.append(f'{item.label} {item.name}: cannot fetch {item.url}: {e}')
            continue
        if size == item.size and sha.hexdigest() == item.sha256:
            print(f'ok      {item.label} {item.name}')
        else:
            bad.append(f'{item.label} {item.name}: {item.url} now serves {size} bytes, '
                       f'sha256 {sha.hexdigest()}; inputs.lock has {item.size}, {item.sha256}')
    for line in bad:
        print(f'CHANGED {line}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
