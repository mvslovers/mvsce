"""Progress output and the one exception type the build raises."""
import sys
import time


class BuildError(Exception):
    """The build cannot go on. The message says why; nothing retries."""


def info(text):
    print(f'[{time.strftime("%H:%M:%S")}] {text}', flush=True)


def fail(text):
    print(f'[{time.strftime("%H:%M:%S")}] ERROR: {text}', file=sys.stderr, flush=True)
