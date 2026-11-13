"""SMP4: what a jobstream applies, and what the CDS says is applied.

A return code says a job ran; the CDS says what it did. applied_by()
reads Jay's SMPCNTL decks for what they APPLY, ACCEPT and RESTORE;
inventory() reads the output of LIST CDS SYSMOD; check() holds the one
to the other.
"""
import re

from .log import BuildError

_COMMENT = re.compile(r'/\*.*?\*/')
_VERB = re.compile(r'\b(APPLY|ACCEPT|RESTORE)\b\s+SELECT\s*\(([^)]*)\)', re.S)
_ENTRY = re.compile(r'^(\S{1,8})\s+TYPE\s+=\s+(\S+)')
_STATUS = re.compile(r'^\s+STATUS\s+=\s+(.*\S)')
_LASTSUP = re.compile(r'^\s+LASTSUP\s+=\s+(\S+)')


def applied_by(jcl_text):
    """What a jobstream leaves behind: {sysmod: 'APP' or 'ACC'}.

    APPLY and ACCEPT with SELECT(...) in the order they appear; RESTORE
    takes a SYSMOD out again (Jay's #DYPDMY is applied and restored).
    """
    lines = [line[:72] for line in jcl_text.splitlines()]
    text = '\n'.join(_COMMENT.sub(' ', line) for line in lines
                     if not line.startswith('//*'))
    state = {}
    for m in _VERB.finditer(text):
        verb = m.group(1)
        for sysmod in (t for t in re.split(r'[\s,]+', m.group(2)) if t):
            if verb == 'RESTORE':
                state.pop(sysmod, None)
            elif verb == 'ACCEPT':
                state[sysmod] = 'ACC'
            else:
                state.setdefault(sysmod, 'APP')
    return state


def inventory(listing):
    """{sysmod: (type, status words, superseded by)} from LIST CDS SYSMOD."""
    result = {}
    current = None
    for line in listing.splitlines():
        m = _ENTRY.match(line)
        if m:
            current = m.group(1)
            result[current] = [m.group(2), (), None]
            continue
        if not current:
            continue
        s = _STATUS.match(line)
        if s and not result[current][1]:
            result[current][1] = tuple(s.group(1).split())
        sup = _LASTSUP.match(line)
        if sup:
            result[current][2] = sup.group(1)
    return {k: tuple(v) for k, v in result.items()}


def _has(inv, sysmod, state, depth=0):
    """True if sysmod has state, or is superseded by a SYSMOD that has it."""
    if sysmod not in inv or depth > 10:
        return False
    typ, status, lastsup = inv[sysmod]
    if state in status:
        return True
    return typ == 'SUPERSEDED' and lastsup is not None and _has(inv, lastsup, state, depth + 1)


def check(inv, expected):
    """Raise unless every SYSMOD in expected ({id: 'APP'|'ACC'}) has that state."""
    missing = sorted(i for i in expected if i not in inv)
    wrong = sorted(f'{i} wants {st}, is {" ".join(inv[i][1]) or inv[i][0]}'
                   for i, st in expected.items() if i in inv and not _has(inv, i, st))
    problems = []
    if missing:
        problems.append('not in the CDS: ' + ' '.join(missing))
    if wrong:
        problems.append('; '.join(wrong))
    if problems:
        raise BuildError('SMP: ' + '; '.join(problems))


def summary(inv):
    counts = {}
    for typ, status, _ in inv.values():
        key = f'{typ} {" ".join(w for w in status if w in ("APP", "ACC"))}'.strip()
        counts[key] = counts.get(key, 0) + 1
    return ', '.join(f'{n} {k}' for k, n in sorted(counts.items()))
