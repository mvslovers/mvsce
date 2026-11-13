"""S2: SMP4 and the distribution libraries (Jay Moseley V8, chapter 3).

Part 1 (conf/smp1.cnf): IPL the starter system with CLPA, format the
spool, attach the three new volumes and run SMP4P44, which installs SMP4
and initialises SMP000, WORK00 and WORK01.

Part 2 (conf/smp2.cnf): IPL again; SMPMOUNT comes in from the reader with
JES2 and mounts SMP000 as PRIVATE. Then SMPJOB00 to SMPJOB07 build the
distribution libraries on SMP000 from the product, PTF and J90012 tapes.

Jay's console is a telnet 3215; patch 0001 makes it the integrated
3215-C so the build drives it through stdin.
"""
from ..log import info
from ..mvs import Console, allocate_tape, mount_tape, reply_rule

NAME = 's2'
TITLE = 'distribution libraries'

VOLUMES = [
    ('work00.3350', '3350', '111111'),
    ('work01.3350', '3350', '222222'),
    ('smp000.3350', '3350', '333333'),
]

U = reply_rule('IEC507D', 'U')   # use the volume despite the open data set


def tape(job, volser, path):
    """A job's tape, whichever way MVS asks for it: IEF238D while drive
    170 is offline (the first tape job after an IPL), IEF233A or IEC501A
    once it is online (measured 2026-11-13: SMPJOB02 asks IEC501A M
    170,PTFS20, SMPJOB04 IEF233A M 170,J90012)."""
    return [allocate_tape(job, path), mount_tape(volser, path)]

# job, JCL, operator rules, expected condition codes (steps not named: 0000),
# timeout in seconds, number of jobs of that name, number of steps (where
# Jay gives it). Codes as Jay's text gives them.
JOBS = [
    ('SMPJOB00', 'jcl/smpjob00.jcl', [], {'IEHPROGM': '0008', 'SMP DLBUCL': '0008'}, 600, 1, None),
    ('SMPJOB01', 'jcl/smpjob01.jcl', tape('SMPJOB01', 'MVS38J', 'tape/zdlib1.het'), {}, 1800, 1, None),
    ('SMPJOB02', 'jcl/smpjob02.jcl', tape('SMPJOB02', 'PTFS20', 'tape/ptfs.het'), {}, 1800, 1, None),
    ('SMPJOB03', 'jcl/smpjob03.jcl', [], {'SMP DLBUCL4': '0004'}, 3600, 1, None),
    ('SMPJOB04', 'jcl/smpjob04.jcl', tape('SMPJOB04', 'J90012', 'tape/j90012.het'), {}, 1800, 1, None),
    ('SMPJOB05', 'jcl/smpjob05.jcl', [], {'SMP DLBUCL': '0004'}, 1800, 1, None),
    ('SMPJOB06', 'jcl/smpjob06.jcl', [], {'SMP DLBUCL': '0004'}, 1800, 1, None),
    # SMPJOB07 submits a second SMPJOB07 (LINK UTILITIES) through the
    # internal reader: Jay's nine steps are 3 + 6.
    ('SMPJOB07', 'jcl/smpjob07.jcl', [U], {}, 1800, 2, 9),
]


def _start(ctx, herc):
    herc.wait_for(r'HHC00414I 0:0151', 60, since=0, what='Hercules start')
    return Console(herc, ctx.tree)


def run(ctx):
    for name, devtype, volser in VOLUMES:
        ctx.dasd.create(ctx.tree / 'dasd' / name, devtype, volser)

    info('  part 1: SMP4')
    with ctx.hercules('conf/smp1.cnf') as herc:
        con = _start(ctx, herc)
        con.ipl('150', [('IEA101A', 'clpa'), ('$HASP426', 'format,noreq'),
                        ('$HASP436', 'y')])
        since = herc.mark()
        herc.send('script conf/dlibs.script')
        herc.wait_for(r'HHC00414I 0:014A', 60, since=since, what='attach 148-14A')
        con.run_job('SMP4P44', 'jcl/smp4p44.jcl', [
            *tape('SMP4P44', 'MVS38J', 'tape/zdlib1.het'),
            mount_tape('T74172', 'tape/smp4b.het'),
            U,
            reply_rule('IEH841D', 'U'),     # initialise 148, 149, 14A
        ], {}, 900)
        con.shutdown()

    info('  part 2: distribution libraries')
    with ctx.hercules('conf/smp2.cnf') as herc:
        con = _start(ctx, herc)
        since = herc.mark()
        con.ipl('150', [('IEA101A', ''), ('$HASP426', 'noreq')], ready=False)
        con.run_job('SMPMOUNT', None, [reply_rule('IEF166D', 'y')], {}, 600, since=since)
        for job, jcl, rules, expect, timeout, count, steps in JOBS:
            con.run_job(job, jcl, rules, expect, timeout, count=count, steps=steps)
        con.shutdown()


# The distribution libraries and the SMP data sets on SMP000, as the first
# verified build left them (2026-11-13).
DLIB_DATASETS = [
    'SYS1.ACMDLIB', 'SYS1.AGENLIB', 'SYS1.AHELP', 'SYS1.AIMAGE',
    'SYS1.ALPALIB', 'SYS1.AMACLIB', 'SYS1.AMODGEN', 'SYS1.AOS00',
    'SYS1.AOS03', 'SYS1.AOS04', 'SYS1.AOS05', 'SYS1.AOS06', 'SYS1.AOS07',
    'SYS1.AOS11', 'SYS1.AOS12', 'SYS1.AOS20', 'SYS1.AOS21', 'SYS1.AOS24',
    'SYS1.AOS26', 'SYS1.AOS29', 'SYS1.AOS32', 'SYS1.AOSA0', 'SYS1.AOSA1',
    'SYS1.AOSB0', 'SYS1.AOSB3', 'SYS1.AOSBN', 'SYS1.AOSC2', 'SYS1.AOSC5',
    'SYS1.AOSC6', 'SYS1.AOSCA', 'SYS1.AOSCD', 'SYS1.AOSCE', 'SYS1.AOSD0',
    'SYS1.AOSD7', 'SYS1.AOSD8', 'SYS1.AOSG0', 'SYS1.AOSH1', 'SYS1.AOSH3',
    'SYS1.AOST3', 'SYS1.AOST4', 'SYS1.AOSU0', 'SYS1.APARMLIB',
    'SYS1.APROCLIB', 'SYS1.ASAMPLIB', 'SYS1.ATCAMMAC', 'SYS1.ATSOMAC',
    'SYS1.AUADS', 'SYS1.HASPSRC', 'SYS1.SMPACDS', 'SYS1.SMPACRQ',
    'SYS1.SMPMTS', 'SYS1.SMPPTS', 'SYS1.SMPSTS',
]


def verify(ctx):
    names = ctx.dasd.check(ctx.tree / 'dasd' / 'smp000.3350', 'SMP000', DLIB_DATASETS)
    ctx.dasd.check(ctx.tree / 'dasd' / 'work00.3350', 'WORK00', [])
    ctx.dasd.check(ctx.tree / 'dasd' / 'work01.3350', 'WORK01', [])
    info(f'  SMP000: {len(names)} data sets')
