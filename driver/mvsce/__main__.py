"""mvsce build driver.

    ./sysgen build [--until STAGE] [--no-cache]
    ./sysgen stages
    ./sysgen fetch
"""
import argparse
import sys
from pathlib import Path

from . import build, inputs
from .log import BuildError, fail, info
from .stages import STAGES

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    p = argparse.ArgumentParser(prog='sysgen', description='Build MVS/CE.')
    p.add_argument('--work', default=str(ROOT / 'build'),
                   help='build directory (default: build/)')
    p.add_argument('--cache', default=str(ROOT / 'cache'),
                   help='input and stage cache (default: cache/)')
    p.add_argument('--hercules', default='hercules', help='Hercules binary')
    sub = p.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build', help='run the stages')
    b.add_argument('--until', help='last stage to run')
    b.add_argument('--no-cache', action='store_true',
                   help='run every stage, neither restore nor save results')
    sub.add_parser('stages', help='list the stages')
    sub.add_parser('fetch', help='fetch and verify the inputs of the selected label')
    args = p.parse_args(argv)

    try:
        if args.command == 'stages':
            for s in STAGES:
                print(f'{s.NAME:4} {s.TITLE}')
        elif args.command == 'fetch':
            label = inputs.load_config(ROOT / 'config' / 'sysgen.toml')['jay']['label']
            for item in inputs.select(inputs.load_lock(ROOT / 'inputs.lock'), label):
                info(f'{inputs.fetch(item, args.cache)}: verified')
        else:
            build.build(ROOT, args.work, args.cache, until=args.until,
                        use_cache=not args.no_cache, hercules_bin=args.hercules)
    except BuildError as e:
        fail(str(e))
        return 1
    except KeyboardInterrupt:
        fail('interrupted')
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
