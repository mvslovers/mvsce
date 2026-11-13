"""Hercules as a child process, driven through its command line.

Hercules runs with stdin and stdout as pipes: commands go to stdin, every
message (Hercules' own and the integrated console's) comes back on stdout
and is written to the stage's log. A reader thread collects the lines;
waits search them from a position the caller marks, so a message that
arrived before the command it answers is not mistaken for the answer.

Every wait has a timeout. A timeout, an unexpected Hercules exit or one of
the fatal messages below raises BuildError with the tail of the log;
nothing is retried.
"""
import re
import subprocess
import threading
import time

from .log import BuildError

# Messages after which the run cannot succeed.
FATAL = [
    re.compile(r'Creating crash dump'),
    re.compile(r'APPEARS TO BE HUNG'),
    re.compile(r'HHC00839E'),        # IPL failed
    re.compile(r'HHC01023W'),        # console port busy
]

PSW = re.compile(r'HHC02278I Processor CP00 PSW: ([0-9A-F]{8}) ([0-9A-F]{8})')


def version(binary='hercules'):
    """The HHC01413I version string, part of every stage cache key."""
    try:
        out = subprocess.run([binary, '--version'], capture_output=True,
                             text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BuildError(f'cannot run {binary}: {e}') from e
    m = re.search(r'HHC01413I (Hercules version \S+)', out)
    if not m:
        raise BuildError(f'{binary} --version printed no HHC01413I line')
    return m.group(1)


class Hercules:
    def __init__(self, config, cwd, log_path, binary='hercules'):
        self.lines = []
        self.cwd = cwd
        self._cond = threading.Condition()
        self._log = open(log_path, 'a', encoding='utf-8', errors='replace')
        self._log.write(f'\n===== hercules -f {config} (in {cwd}) =====\n')
        try:
            self.proc = subprocess.Popen(
                [binary, '-f', str(config)], cwd=cwd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                errors='replace')
        except OSError as e:
            self._log.close()
            raise BuildError(f'cannot start {binary}: {e}') from e
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.quit()

    def _read(self):
        for line in self.proc.stdout:
            line = line.rstrip('\n')
            self._log.write(line + '\n')
            self._log.flush()
            with self._cond:
                self.lines.append(line)
                self._cond.notify_all()
        with self._cond:
            self._cond.notify_all()

    def mark(self):
        with self._cond:
            return len(self.lines)

    def tail(self, n=40):
        with self._cond:
            return '\n'.join(self.lines[-n:])

    def send(self, command):
        if self.proc.poll() is not None:
            raise BuildError(f'Hercules has exited (rc {self.proc.returncode}); '
                             f'cannot send {command!r}\n{self.tail()}')
        self._log.write(f'>>> {command}\n')
        self.proc.stdin.write(command + '\n')
        self.proc.stdin.flush()

    def wait_for(self, pattern, timeout, since=None, fail=(), what=None):
        """Wait for a line matching pattern; return the match.

        fail: patterns that end the wait with an error when they appear
        first (a utility's error message, say).
        """
        pattern = re.compile(pattern) if isinstance(pattern, str) else pattern
        fail = [re.compile(f) if isinstance(f, str) else f for f in fail]
        pos = self.mark() if since is None else since
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                while pos < len(self.lines):
                    line = self.lines[pos]
                    pos += 1
                    for f in FATAL + fail:
                        if f.search(line):
                            raise BuildError(f'{what or pattern.pattern}: '
                                             f'stopped by {line!r}\n{self._tail_locked()}')
                    m = pattern.search(line)
                    if m:
                        return m
                if self.proc.poll() is not None and not self._reader.is_alive():
                    raise BuildError(f'Hercules exited (rc {self.proc.returncode}) '
                                     f'while waiting for {what or pattern.pattern}\n'
                                     f'{self._tail_locked()}')
                left = deadline - time.monotonic()
                if left <= 0:
                    raise BuildError(f'timeout after {timeout}s waiting for '
                                     f'{what or pattern.pattern}\n{self._tail_locked()}')
                self._cond.wait(min(left, 1.0))

    def _tail_locked(self, n=40):
        return '\n'.join(self.lines[-n:])

    def psw(self):
        since = self.mark()
        self.send('psw')
        m = self.wait_for(PSW, 10, since=since, what='PSW display')
        return m.group(1) + m.group(2)

    def wait_psw(self, suffix, timeout, since=None, fail=(), what=None, poll=1.0):
        """Poll the PSW until it ends in suffix (a wait state code).

        Lines arriving meanwhile are checked against FATAL and fail.
        """
        fail = [re.compile(f) if isinstance(f, str) else f for f in fail]
        pos = self.mark() if since is None else since
        deadline = time.monotonic() + timeout
        last = ''
        while True:
            last = self.psw()
            with self._cond:
                for line in self.lines[pos:]:
                    for f in FATAL + fail:
                        if f.search(line):
                            raise BuildError(f'{what or "PSW " + suffix}: stopped by '
                                             f'{line!r}\n{self._tail_locked()}')
                pos = len(self.lines)
            if last.endswith(suffix):
                return last
            if time.monotonic() > deadline:
                raise BuildError(f'timeout after {timeout}s waiting for PSW ...{suffix} '
                                 f'({what}); last PSW {last}\n{self.tail()}')
            time.sleep(poll)

    def quit(self, timeout=60):
        """Quit Hercules and wait for the process: only its exit releases
        the DASD files and sockets."""
        if self.proc.poll() is None:
            try:
                self.send('quit')
            except (BuildError, OSError):
                pass
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        self._reader.join(timeout=10)
        self._log.close()
