"""S1: the MVS 3.7 starter system (Jay Moseley V8, "Building the Starter System").

Creates START1 and SPOOL0 (3330) and fills each in two standalone runs
from the starter tapes: DASDI initialises the volume, DUMP/RESTORE
restores it. The control cards are Jay's sajobs, read from the 1442s at
00C-00F (conf/ibcdmprs.cnf).

Each run: IPL the tape, wait for the utility's console read (PSW ...FFFF),
name the input device, wait for IBC163A END OF JOB and the utility's
final wait state: ...1111 after DASDI, ...EEEE after DUMP/RESTORE.

Measured 2026-11-13 on Hercules 4.10.0.11800: the whole stage takes about
20 seconds. Jay's text says to enter a lone "/" before the input device;
sent through stdin that empty line answers IBC105A itself and DASDI ends
with IBC102A CONTROL STATEMENT ERROR, so the device is sent directly.
"""
from ..log import info

NAME = 's1'
TITLE = 'starter system'

VOLUMES = [
    # file in dasd/, device type, volser dasdinit writes, volser afterwards
    ('start1.3330', '3330', '111111', 'START1'),
    ('spool0.3330', '3330', '222222', 'SPOOL0'),
]

RUNS = [
    # tape, reader, final PSW, what
    ('280', '00c', '1111', 'DASDI START1'),
    ('280', '00d', 'EEEE', 'DUMP/RESTORE START1'),
    ('281', '00e', '1111', 'DASDI SPOOL0'),
    ('281', '00f', 'EEEE', 'DUMP/RESTORE SPOOL0'),
]

# Any IBC message with ERROR in it, or a job that terminates.
UTILITY_ERRORS = [r'IBC\d{3}[A-Z] .*ERROR', r'JOB TERMINATE']

MANIFEST = {
    'start1.3330': ('START1', [
        'SYS1.BRODCAST', 'SYS1.CDS', 'SYS1.CMDLIB', 'SYS1.DCMLIB', 'SYS1.DSSVM',
        'SYS1.DUMP00', 'SYS1.HLDS', 'SYS1.IMAGELIB', 'SYS1.LINKLIB',
        'SYS1.LOGREC', 'SYS1.LPALIB', 'SYS1.MANX', 'SYS1.MANY', 'SYS1.NUCLEUS',
        'SYS1.PARMLIB', 'SYS1.PROCLIB', 'SYS1.PTS', 'SYS1.SVCLIB', 'SYS1.UADS',
    ]),
    'spool0.3330': ('SPOOL0', ['SYS1.HASPACE', 'SYS1.HASPCKPT']),
}


def run(ctx):
    for name, devtype, volser, _ in VOLUMES:
        ctx.dasd.create(ctx.tree / 'dasd' / name, devtype, volser)
    with ctx.hercules('conf/ibcdmprs.cnf') as herc:
        herc.wait_for(r'HHC00221I 0:0281', 60, since=0, what='Hercules start')
        for tape, reader, done, what in RUNS:
            info(f'  {what}')
            since = herc.mark()
            herc.send(f'ipl {tape}')
            herc.wait_psw('FFFF', 60, since=since, fail=UTILITY_ERRORS,
                          what=f'{what}: console read')
            since = herc.mark()
            herc.send(f'/input=1442,{reader}')
            herc.wait_for(r'IBC163A\s+END OF JOB', 600, since=since,
                          fail=UTILITY_ERRORS, what=f'{what}: end of job')
            herc.wait_psw(done, 60, since=since, fail=UTILITY_ERRORS,
                          what=f'{what}: final wait state')
            herc.send('stop')


def verify(ctx):
    for name, (volser, datasets) in MANIFEST.items():
        ctx.dasd.check(ctx.tree / 'dasd' / name, volser, datasets)
