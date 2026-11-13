"""S3: the system generation (Jay Moseley V8, "Performing a System Generation").

On the starter system (conf/sysgen.cnf): SYSGEN00 initialises and
catalogs the new volumes MVSRES, MVS000, SPOOL1 and PAGE00; SYSGEN01
assembles stage 1 and writes the stage 2 deck to tape/stage1.het. The
deck is turned into jcl/stage2.jcl (stage2() below, Jay's stage2.awk),
submitted held, and its six jobs are released one by one. Then JES2
(SYSGEN02), the private macros (SYSGEN03), parmlib/proclib and SMP
set-up (SYSGEN04), TSO/VTAM (SYSGEN05), the PTFs the usermods need
(SYSGEN06), the usermods as Jay's one jobstream (USERMODS) and ICKDSF
R13 (FDZ1D02).

The expected condition codes are Jay's.
"""
import subprocess

from ..log import BuildError, info
from ..mvs import Console, allocate_tape, mount_tape, reply_rule

NAME = 's3'
TITLE = 'system generation'

VOLUMES = [
    ('mvsres.3350', '3350', '111111'),
    ('mvs000.3350', '3350', '222222'),
    ('spool1.3350', '3350', '333333'),
    ('page00.3350', '3350', '444444'),
]


def tape(job, volser, path):
    return [allocate_tape(job, path), mount_tape(volser, path)]


def stage2(deck):
    """Jay's stage2.awk in Python: stage 1 output -> stage 2 JCL.

    Every job card gets TYPRUN=HOLD,TIME=1439, a JOBPARM and the target
    master catalog as JOBCAT (SYSGEN6 already has TYPRUN=HOLD and only
    gets the JOBPARM); EXPDT=99350 becomes 00000; STEPY runs IEFBR14
    instead of IDCAMS; empty cards and the deck separator are dropped.
    """
    out = []

    def card_job(line):
        out.append(line.rstrip(' \t\r\n') + ',')
        out.append('//             TYPRUN=HOLD,TIME=1439')
        out.append('/*JOBPARM LINES=100')
        out.append('//JOBCAT   DD  DSN=SYS1.VSAM.MASTER.CATALOG,DISP=SHR')

    for line in deck.splitlines():
        if ' JOB ' in line:
            first = line.split()[0] if line.split() else ''
            if first == '//SYSGEN1':
                card_job(line)
            elif first == '//SYSGEN6':
                out.append('//')
                out.append(line)
            else:
                out.append('//')
                card_job(line)
        elif ' TYPRUN=HOLD' in line:
            out.append(line)
            out.append('/*JOBPARM LINES=100')
        elif 'EXPDT=99350' in line:
            out.append(line.replace('99350', '00000', 1))
        elif 'STEPY' in line:
            out.append('//STEPY EXEC PGM=IEFBR14')
        elif line == '' or line[:10] == '||||||||||':
            continue
        else:
            out.append(line)
    out.append('//')
    return '\n'.join(out) + '\n'


def _hetget(ctx, het, out, file_no):
    r = subprocess.run(['hetget', '-a', het, out, str(file_no)], cwd=ctx.tree,
                       capture_output=True, text=True, errors='replace')
    if r.returncode != 0 or not (ctx.tree / out).exists():
        raise BuildError(f'hetget {het} file {file_no} failed (rc {r.returncode}):\n'
                         f'{r.stdout}{r.stderr}')


U = reply_rule('IEC507D', 'U')

# SYSGEN1-6, released one by one: job, expected codes, number of steps.
# Jay: SYSGEN1 has six link steps ending 0004, SYSGEN2 three, SYSGEN6's
# STEPZ1 ends 0008; measured 2026-11-13 which ones.
W = '0004'
STAGE2_JOBS = [
    ('SYSGEN1', {'LK SG19': W, 'LK SG28': W, 'LK SG29': W, 'LK SG31': W, 'LK SG32': W,
                 'LK SG37': W}, 40),
    ('SYSGEN2', {'LK SG8': W, 'LK SG13': W, 'LK SG33': W}, 45),
    ('SYSGEN3', {}, 3),
    ('SYSGEN4', {}, 17),
    ('SYSGEN5', {}, 20),
    ('SYSGEN6', {'STEPZ1': '0008'}, 5),
]


def run(ctx):
    for name, devtype, volser in VOLUMES:
        ctx.dasd.create(ctx.tree / 'dasd' / name, devtype, volser)

    with ctx.hercules('conf/sysgen.cnf') as herc:
        herc.wait_for(r'HHC00414I 0:0249', 60, since=0, what='Hercules start')
        con = Console(herc, ctx.tree, loaded={'170': 'tape/stage1.het'})
        con.ipl('150', [('IEA101A', 'clpa'), ('$HASP426', 'noreq')])
        since = herc.mark()
        herc.send('script conf/sysgen.script')
        herc.wait_for(r'HHC00414I 0:014C', 60, since=since, what='attach 149-14C')

        con.run_job('SYSGEN00', 'jcl/sysgen00.jcl', [
            reply_rule('ICK003D', 'U'),     # initialise 149-14C
            reply_rule('IEF166D', 'Y'),     # the embedded MOUNT commands
        ], {'IEHPROGM': '0008'}, 1800, count=3, steps=9)

        con.run_job('SYSGEN01', 'jcl/sysgen01.jcl', [U], {'CLEANUP': '0008'},
                    1800, count=2, steps=4)

        info('  stage 2 deck: tape/stage1.het -> jcl/stage2.jcl')
        _hetget(ctx, 'tape/stage1.het', 'stage1.output', 1)
        deck = (ctx.tree / 'stage1.output').read_text(errors='replace')
        (ctx.tree / 'jcl' / 'stage2.jcl').write_text(stage2(deck))

        submitted = herc.mark()
        herc.send('devinit 12 jcl/stage2.jcl')
        herc.wait_for(r'\$HASP101 SYSGEN6\s+HELD', 300, since=submitted,
                      what='stage 2 jobs read in and held')
        for job, expect, steps in STAGE2_JOBS:
            con.run_job(job, None, [U], expect, 3600, since=submitted,
                        commands=[f"$a'{job.lower()}'"], steps=steps)

        con.run_job('SYSGEN02', 'jcl/sysgen02.jcl', [U], {}, 1800, steps=5)
        con.run_job('SYSGEN03', 'jcl/sysgen03.jcl',
                    tape('SYSGEN03', 'PVTMAC', 'tape/apvtmacs.het') + [U], {}, 1800, steps=1)
        # SUBMIT10 submits a second SYSGEN04 (JCLIN) through the internal reader.
        con.run_job('SYSGEN04', 'jcl/sysgen04.jcl', [U], {}, 1800, count=2, steps=25)
        con.run_job('SYSGEN05', 'jcl/sysgen05.jcl', [U], {}, 1800, steps=14)
        con.run_job('SYSGEN06', 'jcl/sysgen06.jcl', [U], {'HMASMP SMPAPP': W}, 3600, steps=1)
        # Jay's usermods as he ships them: seven jobs, 159 steps, four 0004.
        con.run_job('USERMODS', 'jcl/usermods.jcl',
                    tape('USERMODS', 'SMPPTF', 'tape/usermods.het') + [U],
                    {'HMASMP UMOD001': W, 'HMASMP UMOD007': W, 'HMASMP UMOD009': W,
                     'HMASMP UMOD032': W}, 7200, count=7, steps=159)
        con.run_job('FDZ1D02', 'jcl/fdz1d02.jcl',
                    tape('FDZ1D02', 'MVS38J', 'tape/dz1d02.het') + [U], {}, 1800,
                    count=2, steps=5)
        con.shutdown()


# Non-VSAM data sets on the new volumes after the first verified build
# (2026-11-13). VSAM data spaces and the page data sets carry generated
# names and are not listed.
MANIFEST = {
    'mvsres.3350': [
        'SYS1.BRODCAST', 'SYS1.CMDLIB', 'SYS1.DCMLIB', 'SYS1.DUMP00', 'SYS1.DUMP01',
        'SYS1.DUMP02', 'SYS1.HELP', 'SYS1.IMAGELIB', 'SYS1.INDMAC', 'SYS1.LINKLIB',
        'SYS1.LOGREC', 'SYS1.LPALIB', 'SYS1.MACLIB', 'SYS1.MANX', 'SYS1.MANY',
        'SYS1.NUCLEUS', 'SYS1.PARMLIB', 'SYS1.PROCLIB', 'SYS1.SAMPLIB', 'SYS1.SVCLIB',
        'SYS1.TCOMMAC', 'SYS1.TELCMLIB', 'SYS1.UADS', 'SYS1.VTAMLIB',
    ],
    'mvs000.3350': [
        'SYS1.APVTMACS', 'SYS1.CMDPROC', 'SYS1.HASPCKPT', 'SYS1.VTAMLST', 'SYS1.VTAMSRC',
        'SYS2.CMDLIB', 'SYS2.CONTROL', 'SYS2.HELP', 'SYS2.LINKLIB', 'SYS2.PROCLIB',
    ],
    'spool1.3350': ['SYS1.HASPACE'],
    'page00.3350': [],
}


def verify(ctx):
    for name, volser in (('mvsres.3350', 'MVSRES'), ('mvs000.3350', 'MVS000'),
                         ('spool1.3350', 'SPOOL1'), ('page00.3350', 'PAGE00')):
        names = ctx.dasd.check(ctx.tree / 'dasd' / name, volser, MANIFEST.get(name, []))
        info(f'  {volser}: {len(names)} data sets')
