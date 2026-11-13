"""MVS on the integrated console: IPL replies, jobs, operator rules, shutdown.

A job runs from devinit of the card reader until JES2 purges it
($HASP250 ... IS PURGED, after it has printed). While it runs, every new
console line goes through the job's operator rules: a rule matches a
message and acts (mount a tape, reply). A WTOR (*nn) that no rule
answers ends the build at once instead of leaving the job waiting. So
does an abend (IEF450I).

The result is read from the 1403 printer file: one IEF142I line per step
with its condition code. Every step must appear and match the job's
expected codes; steps not named there must end with 0000.
"""
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .log import BuildError, info

# Measuring mode (--record): condition codes that differ from the
# expectation are collected here instead of stopping the build. The build
# fails at the end all the same and caches nothing.
record = None

WTOR = re.compile(r'\*(\d+) (\S+)')
IEF142 = re.compile(r'IEF142I (\S+) (\S+)(?: (\S+))? - STEP WAS EXECUTED - COND CODE (\d{4})')
# MVS repeats a mount request nobody has answered after some minutes;
# then the job waits for a tape no rule mounts.
MOUNT_PENDING = re.compile(r'IGF991E\s+MOUNT PENDING')
# A JES2 command naming a job JES2 does not have.
JOB_NOT_FOUND = re.compile(r'\$HASP000 (\S+)\s+JOB NOT FOUND')
# K = demount: the drive is empty afterwards.
DEMOUNT = re.compile(r'(?:IEF234E|IEC502E) K ([0-9A-F]{3}),')
IEF450 = re.compile(r'IEF450I (\S+) (.*?) - ABEND (\S+ \S+)')


@dataclass
class Rule:
    """pattern: regex on a console line. reply: text for the WTOR the line
    carries (the reply id is taken from the line). commands: Hercules
    commands sent first. mount: (address, tape file) to put on a drive
    first, unless that tape is already on it. once: the rule fires at
    most once per job."""
    pattern: str
    reply: str = None
    commands: list = field(default_factory=list)
    mount: tuple = None
    once: bool = False


def reply_rule(msgid, text, **kw):
    return Rule(rf'\*(\d+) {re.escape(msgid)}', reply=text, **kw)


def allocate_tape(job, tape, address='170'):
    """IEF238D (no tape drive online): put the tape on the drive, then name it."""
    return Rule(rf"\*(\d+) IEF238D {re.escape(job)} ", reply=address,
                mount=(address, tape), once=True)


def mount_tape(volser, tape, address='170'):
    """A mount request for volser on an online drive: IEF233A at
    allocation, IEC501A at OPEN. Mount the tape asked for."""
    return Rule(rf'(?:IEF233A|IEC501A) M {address},{re.escape(volser)},',
                mount=(address, tape))


class Console:
    def __init__(self, herc, tree, printer='prt00e.txt', loaded=None):
        """loaded: {drive address: tape file} the configuration mounts."""
        self.herc = herc
        self.tree = Path(tree)
        self.printer = self.tree / printer
        self.loaded = dict(loaded or {})     # drive address -> tape file on it
        self.pos = 0         # console line where the last job ended

    def mount(self, address, tape):
        """Put tape on the drive, unless it is there already: a second
        devinit of the same tape while MVS opens it ends the OPEN with
        137-0C (measured 2026-11-13, SMPJOB01 after IEF238D + IEF233A)."""
        if self.loaded.get(address) == tape:
            return
        self.herc.send(f'devinit {address} {tape}')
        self.loaded[address] = tape

    def command(self, text):
        """An operator command. Sent on a quiet console only: unlike a WTOR
        reply, nothing in MVS is waiting to read it (see Hercules.wait_quiet)."""
        self.herc.wait_quiet()
        self.herc.send('/' + text)

    def reply(self, msgid, text, timeout=300, since=None):
        """Wait for the WTOR msgid and answer it ('' = Enter)."""
        m = self.herc.wait_for(rf'\*(\d+) {re.escape(msgid)}', timeout, since=since,
                               what=msgid)
        self.herc.send(f'/r {m.group(1)},{text}' if text else '/')
        return m

    def ipl(self, address, replies, timeout=300, ready=True):
        """IPL and answer the start-up WTORs in order.

        replies: (msgid, text) pairs; text '' answers with Enter.
        ready: wait for $HASP099 as well. Without it, the caller watches
        the console itself (a job that starts with JES2, say).
        """
        since = self.herc.mark()
        self.herc.send(f'ipl {address}')
        for msgid, text in replies:
            m = self.herc.wait_for(rf'(?:\*(\d+) )?{re.escape(msgid)}', timeout,
                                   since=since, what=f'IPL: {msgid}')
            since = self.herc.mark()
            if text == '' and m.group(1) is None:
                self.herc.send('/')
            else:
                self.herc.send(f'/r {m.group(1) or 0},{text}')
        if not ready:
            return
        self.herc.wait_for(r'\$HASP099 ALL AVAILABLE FUNCTIONS COMPLETE', timeout,
                           since=since, what='JES2 initialisation')

    def _printer_size(self):
        return self.printer.stat().st_size if self.printer.exists() else 0

    def run_job(self, job, submit=None, rules=(), expect=None, timeout=900, since=None,
                count=1, commands=(), steps=None):
        """Run a job and check its step condition codes.

        The run ends when JES2 has purged as many jobs of this name as it
        has read in ($HASP100 ... ON READER1 or ON INTRDR): Jay's decks
        often carry several jobs of one name, and some submit a follow-on
        job of the same name through the internal reader (SYSGEN04,
        SMPJOB07, FDZ1D02). Their steps are checked together.
        count: how many such jobs there must be; a different number is an
        error (a job that submits one more than expected, say).
        steps: how many steps they must have run together, where Jay says.
        commands: console commands sent first ($A to release a held job).

        submit: the JCL file for the reader; None when the job is already
        on its way in: attached with the reader, or submitted by the job
        before through the internal reader. Then the console is read from
        where the job before ended (or from since).
        expect: {step: cc}; a step in a procedure as 'PROCSTEP STEP', the order
        IEF142I prints them in (SMP DLBUCL for step DLBUCL running proc step SMP).
        """
        start = self._printer_size()
        if since is not None:
            pos = since
        elif submit:
            pos = self.herc.mark()
        else:
            pos = self.pos
        if submit:
            self.herc.send(f'devinit 12 {submit}')
        for cmd in commands:
            self.command(cmd)
        fired = set()
        read_in = purged_n = 0
        entered = re.compile(rf'\$HASP100 {re.escape(job)}\s+ON (?:READER\d+|INTRDR)')
        deadline = time.monotonic() + timeout
        purged = re.compile(rf'\$HASP250 {re.escape(job)}\s+IS PURGED')
        compiled = [(re.compile(r.pattern), r) for r in rules]
        while True:
            base = pos
            lines = self.herc.lines[pos:]
            pos += len(lines)
            for i, line in enumerate(lines):
                if entered.search(line):
                    read_in += 1
                if purged.search(line):
                    purged_n += 1
                    if purged_n >= read_in:
                        self.pos = base + i + 1
                        if purged_n != count:
                            raise BuildError(f'{job}: {purged_n} jobs of this name ran, '
                                             f'expected {count}')
                        return self._check(job, start, expect or {}, steps)
                nf = JOB_NOT_FOUND.search(line)
                if nf:
                    raise BuildError(f'{job}: JES2 has no job {nf.group(1)} '
                                     f'({line.strip()!r})')
                if MOUNT_PENDING.search(line):
                    raise BuildError(f'{job}: {line.strip()!r}: no rule mounts the tape '
                                     f'asked for\n{self.herc.tail()}')
                dm = DEMOUNT.search(line)
                if dm:
                    self.loaded.pop(dm.group(1), None)
                ab = IEF450.search(line)
                if ab and ab.group(1) == job:
                    raise BuildError(f'{job}: step {ab.group(2)} abended {ab.group(3)}\n'
                                     f'{self.herc.tail()}')
                handled = False
                for i, (rx, rule) in enumerate(compiled):
                    if rule.once and i in fired:
                        continue
                    m = rx.search(line)
                    if not m:
                        continue
                    fired.add(i)
                    handled = True
                    if rule.mount:
                        self.mount(*rule.mount)
                    for cmd in rule.commands:
                        self.herc.send(cmd)
                    if rule.reply is not None:
                        rid = WTOR.search(line)
                        if not rid:
                            raise BuildError(f'{job}: rule {rule.pattern!r} has a reply, '
                                             f'but {line!r} is no WTOR')
                        self.herc.send(f'/r {rid.group(1)},{rule.reply}')
                    break
                if not handled:
                    w = WTOR.search(line)
                    if w and line.lstrip('/ ').startswith('*'):
                        raise BuildError(f'{job}: unexpected operator request {line!r}; '
                                         f'no rule answers {w.group(2)}\n{self.herc.tail()}')
            if self.herc.proc.poll() is not None:
                raise BuildError(f'Hercules exited while {job} ran\n{self.herc.tail()}')
            if time.monotonic() > deadline:
                raise BuildError(f'{job}: not finished after {timeout}s\n{self.herc.tail()}')
            time.sleep(0.2)

    def _check(self, job, start, expect, nsteps=None):
        with open(self.printer, 'rb') as f:
            f.seek(start)
            text = f.read().decode('ascii', 'replace')
        steps = []      # (step, cc) in order; a step name may repeat
        for m in IEF142.finditer(text):
            if m.group(1) != job:
                continue
            name = f'{m.group(2)} {m.group(3)}' if m.group(3) else m.group(2)
            steps.append((name, m.group(4)))
        if not steps:
            raise BuildError(f'{job}: no IEF142I step messages in {self.printer.name}')
        ran = {name for name, _ in steps}
        problems = [f'{s} expected {cc}, not run' for s, cc in expect.items() if s not in ran]
        for s, cc in steps:
            want = expect.get(s, '0000')
            if cc != want:
                problems.append(f'{s} ended {cc}, expected {want}')
        if nsteps is not None and len(steps) != nsteps:
            problems.append(f'{len(steps)} steps ran, expected {nsteps}')
        summary = ' '.join(f'{s}={cc}' for s, cc in steps)
        if problems:
            if record is None:
                raise BuildError(f'{job}: ' + '; '.join(problems) + f' ({summary})')
            record.append(f'{job}: ' + '; '.join(problems))
            info(f'  RECORDED {job}: ' + '; '.join(problems))
        info(f'  {job}: {summary}')
        return steps

    def shutdown(self, timeout=300):
        """Jay's sequence: $P JES2, Z EOD, QUIESCE.

        Measured on the starter system (2026-11-13): JES2 ends with
        IEF142I JES2 JES2 ... COND CODE 0000 and the release of
        SYS1.HASPACE; QUIESCE puts the CPU into disabled wait ...0CCC.
        """
        since = self.herc.mark()
        self.command('$p jes2')
        self.herc.wait_for(r'IEF142I JES2 JES2 - STEP WAS EXECUTED - COND CODE 0000',
                           timeout, since=since, what='JES2 end')
        self.herc.wait_for(r'IEF285I\s+SYS1\.HASPACE\s+KEPT', timeout, since=since,
                           what='JES2 spool release')
        since = self.herc.mark()
        self.command('z eod')
        self.herc.wait_for(r'IEE334I HALT\s+EOD SUCCESSFUL', timeout, since=since,
                           what='Z EOD')
        since = self.herc.mark()
        self.command('quiesce')
        self.herc.wait_for(r'HHC00809I Processor CP00: disabled wait state \S+ \S+CCC',
                           timeout, since=since, what='QUIESCE')
