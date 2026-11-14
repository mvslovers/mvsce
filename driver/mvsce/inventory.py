"""The inventory of a system: what it is, as text files that diff well.

    ./sysgen inventory --system DIR --config conf/x.cnf --out DIR

reads a system's Hercules configuration and its DASD images (no IPL) and
writes

    devices.txt            every device the configuration defines
    volumes.txt            address, device type, volser, image file
    datasets/<VOLSER>.txt  every data set: name, DSORG, RECFM, LRECL,
                           BLKSIZE, tracks, extents
    members/<DSN>@<VOLSER>.txt  the members of every partitioned data set,
                           with size and SHA-256 (first 16 digits) of their
                           EBCDIC content; for libraries dasdpdsu cannot
                           unload (load modules, RECFM U) the names only,
                           from dasdcat, marked "names only"
    text/<DSN>/<MEMBER>    the content, as text, of the members of the
                           configuration libraries (TEXT_LIBRARIES)

Dates and space use are left out on purpose: they change with every run,
and the point is to compare two systems (MVS/CE 3.0.0 against a layer of
this build) with diff -r.
"""
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .log import BuildError, info

# Libraries whose content is configuration and is kept as text.
TEXT_LIBRARIES = [
    'SYS1.PARMLIB', 'SYS1.PROCLIB', 'SYS2.PROCLIB', 'SYS1.CMDPROC',
    'SYS2.CMDPROC', 'SYS1.VTAMLST', 'SYS1.SECURE.CNTL', 'SYS2.EXEC',
    'SYS2.CLIST', 'SYS2.CONTROL', 'SYS1.UMODCNTL',
]

DEVICE = re.compile(r'^([0-9A-Fa-f]{3,4}(?:[.-][0-9A-Fa-f]+)?)\s+(\S+)\s*(.*)$')
DASD_TYPES = ('2311', '2314', '3330', '3340', '3350', '3375', '3380', '3390', '9345')


def devices(system, config):
    """[(address, type, rest of the line)] of a Hercules configuration,
    INCLUDE files followed (relative to the system directory)."""
    out = []
    seen = set()

    def read(path):
        if path in seen:
            return
        seen.add(path)
        for raw in (system / path).read_text(errors='replace').splitlines():
            line = raw.split('#', 1)[0].strip()
            if not line:
                continue
            if line.upper().startswith('INCLUDE '):
                inc = line.split(None, 1)[1]
                if (system / inc).exists():
                    read(inc)
                else:
                    out.append(('INCLUDE', inc, '(missing)'))
                continue
            m = DEVICE.match(line)
            if m and (m.group(2)[:4].isdigit() or m.group(2) in ('console', 'tso')):
                out.append((m.group(1).upper(), m.group(2), m.group(3).strip()))
    read(config)
    return out


def _dasdls(image):
    r = subprocess.run(['dasdls', '-hdr', '-info', '-dsnl=44', str(image)],
                       capture_output=True, text=True, errors='replace')
    out = r.stdout + r.stderr
    m = re.search(r'VOLSER:\s+(\S+)', out)
    if not m:
        raise BuildError(f'dasdls {image} failed (rc {r.returncode}):\n{out[-800:]}')
    rows = []
    started = False
    for line in r.stdout.splitlines():
        if line.startswith('Dsname'):
            started = True
            continue
        if not started or not line.strip() or line.startswith(('End of dasdls', 'HHC')):
            continue
        name = line[:44].strip()
        rest = line[45:].split()
        # Created ORG RECFM LRECL BLKSZ Key Trks %Use #Ext 2ndry
        # ORG may be blank: then the fields shift left by one
        if len(rest) >= 2 and rest[1] in ('PS', 'PO', 'DA', 'IS', 'VS'):
            org, fields = rest[1], rest[2:]
        else:
            org, fields = '-', rest[1:]
        recfm, lrecl, blksz, key, trks, _use, ext = (fields + ['-'] * 7)[:7]
        rows.append((name, org, recfm, lrecl, blksz, trks, ext))
    return m.group(1), rows


def _unload(image, dsn, tmp, ascii=False):
    """dasdpdsu one PDS into a fresh directory; {member: bytes}."""
    out = tmp / ('a' if ascii else 'e') / dsn
    out.mkdir(parents=True, exist_ok=True)
    args = ['dasdpdsu', str(image), dsn] + (['ASCII'] if ascii else []) + [str(out)]
    r = subprocess.run(args, capture_output=True, text=True, errors='replace')
    if r.returncode != 0:
        return None
    return {p.stem.upper(): p.read_bytes() for p in sorted(out.iterdir()) if p.is_file()}


def _printable(name):
    """A member name as it is, or as X'..' when it is not plain text (the
    SMP CDS keys its members with binary names)."""
    if re.fullmatch(r'[A-Z0-9@#$]{1,8}', name):
        return name
    return "X'" + name.encode('latin-1', 'replace').hex().upper() + "'"


def _names(image, dsn):
    """Member names of a PDS from dasdcat (works for load libraries too)."""
    r = subprocess.run(['dasdcat', '-i', str(image), f'{dsn}/?'], capture_output=True)
    if r.returncode != 0:
        return None
    lines = r.stdout.decode('latin-1').splitlines()
    return [_printable(l.strip().upper()) for l in lines
            if l.strip() and not l.startswith('HHC')]


def inventory(system, config, out):
    system, out = Path(system), Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / 'datasets').mkdir(parents=True)
    (out / 'members').mkdir()
    (out / 'text').mkdir()

    devs = devices(system, config)
    (out / 'devices.txt').write_text(''.join(f'{a:9} {t:8} {r}\n' for a, t, r in devs))

    vols = []
    texts = 0
    with tempfile.TemporaryDirectory() as tmpname:
        tmp = Path(tmpname)
        for address, devtype, rest in devs:
            if devtype not in DASD_TYPES or not rest:
                continue
            image = system / rest.split()[0]
            if not image.exists():
                vols.append((address, devtype, '(missing)', rest.split()[0]))
                continue
            volser, rows = _dasdls(image)
            vols.append((address, devtype, volser, rest.split()[0]))
            (out / 'datasets' / f'{volser}.txt').write_text(''.join(
                f'{n:44} {o:3} {rf:5} {lr:>5} {bs:>5} {tr:>5} {ex:>3}\n'
                for n, o, rf, lr, bs, tr, ex in sorted(rows)))
            for name, org, recfm, lrecl, *_ in rows:
                if org != 'PO':
                    continue
                target = out / 'members' / f'{name}@{volser}.txt'
                members = _unload(image, name, tmp) if recfm.startswith('F') else None
                if members is not None:
                    target.write_text(''.join(
                        f'{m:8} {len(b):8} {hashlib.sha256(b).hexdigest()[:16]}\n'
                        for m, b in sorted(members.items())))
                else:
                    names = _names(image, name)
                    if names is None:
                        raise BuildError(f'{image}: cannot read the directory of {name}')
                    target.write_text('# names only\n' + ''.join(f'{m}\n' for m in sorted(names)))
                if name in TEXT_LIBRARIES and lrecl == '80':
                    text = _unload(image, name, tmp, ascii=True) or {}
                    d = out / 'text' / f'{name}@{volser}'
                    d.mkdir()
                    for m, b in text.items():
                        (d / m).write_bytes(b)
                        texts += 1
            info(f'  {address} {devtype} {volser}: {len(rows)} data sets')
    (out / 'volumes.txt').write_text(''.join(f'{a:9} {t:5} {v:9} {f}\n' for a, t, v, f in vols))
    info(f'inventory: {len(vols)} volumes, {texts} configuration members -> {out}')


def _read_members(path):
    lines = path.read_text().splitlines()
    names_only = bool(lines) and lines[0] == '# names only'
    out = {}
    for l in lines[1:] if names_only else lines:
        parts = l.split()
        if parts:
            out[parts[0]] = None if names_only else tuple(parts[1:3])
    return out


def _by_name(inv, sub, suffix='.txt'):
    """{dsname: path} for members/ or text/ entries, volser dropped."""
    out = {}
    for p in sorted((inv / sub).iterdir()):
        name = p.name[:-len(suffix)] if suffix and p.name.endswith(suffix) else p.name
        out.setdefault(name.split('@')[0], p)
    return out


# VSAM data spaces are named from the time of their DEFINE.
VOLATILE = re.compile(r'^(Z999999\d\.VSAMDSPC|VSAMDSET\.T[0-9A-F]+\.DFD\d+)\.')


def diff(a, b, out=None, label_a='A', label_b='B'):
    """A Markdown report of how inventory b differs from inventory a."""
    a, b = Path(a), Path(b)
    lines = [f'# Inventory difference: {label_a} → {label_b}', '']

    def volumes(inv):
        return {l.split()[2]: l.split()[:2] for l in (inv / 'volumes.txt').read_text().splitlines()}
    va, vb = volumes(a), volumes(b)
    lines += ['## Volumes', '', f'| volser | {label_a} | {label_b} |', '|---|---|---|']
    for v in sorted(set(va) | set(vb)):
        fa = ' '.join(va.get(v, ['–'])) if v in va else '–'
        fb = ' '.join(vb.get(v, ['–'])) if v in vb else '–'
        lines.append(f'| {v} | {fa} | {fb} |')

    def datasets(inv):
        out = {}
        for p in (inv / 'datasets').glob('*.txt'):
            for l in p.read_text().splitlines():
                parts = l.split()
                if not VOLATILE.match(parts[0]):
                    out.setdefault(parts[0], (p.stem, parts[1:5]))
        return out
    da, db = datasets(a), datasets(b)
    only_a = sorted(set(da) - set(db))
    only_b = sorted(set(db) - set(da))
    lines += ['', f'## Data sets only in {label_a} ({len(only_a)})', '']
    lines += [f'- `{n}` on {da[n][0]} ({" ".join(da[n][1])})' for n in only_a] or ['none']
    lines += ['', f'## Data sets only in {label_b} ({len(only_b)})', '']
    lines += [f'- `{n}` on {db[n][0]} ({" ".join(db[n][1])})' for n in only_b] or ['none']

    ma, mb = _by_name(a, 'members'), _by_name(b, 'members')
    lines += ['', '## Libraries in both: members', '',
              '| library | only in ' + label_a + ' | only in ' + label_b + ' | changed |', '|---|---|---|---|']
    for lib in sorted(set(ma) & set(mb)):
        xa, xb = _read_members(ma[lib]), _read_members(mb[lib])
        oa, ob = sorted(set(xa) - set(xb)), sorted(set(xb) - set(xa))
        ch = sorted(m for m in set(xa) & set(xb)
                    if xa[m] is not None and xb[m] is not None and xa[m][1] != xb[m][1])
        if oa or ob or ch:
            def fmt(x):
                return (', '.join(x[:12]) + (f' … (+{len(x) - 12})' if len(x) > 12 else '')) if x else ''
            lines.append(f'| `{lib}` | {fmt(oa)} | {fmt(ob)} | {fmt(ch)} |')

    ta, tb = _by_name(a, 'text', suffix=''), _by_name(b, 'text', suffix='')
    lines += ['', '## Configuration members that differ', '']
    for lib in sorted(set(ta) | set(tb)):
        pa, pb = ta.get(lib), tb.get(lib)
        names = sorted({p.name for p in (pa.iterdir() if pa else [])} |
                       {p.name for p in (pb.iterdir() if pb else [])})
        for n in names:
            fa = pa / n if pa and (pa / n).exists() else None
            fb = pb / n if pb and (pb / n).exists() else None
            if fa and fb and fa.read_bytes() == fb.read_bytes():
                continue
            state = ('only in ' + label_a) if not fb else ('only in ' + label_b) if not fa else 'differs'
            lines.append(f'- `{lib}({n})`: {state}')
    text = '\n'.join(lines) + '\n'
    if out:
        Path(out).write_text(text)
        info(f'inventory diff -> {out}')
    return text
