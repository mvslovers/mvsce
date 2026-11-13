"""S5: a normal start of the finished system (Jay Moseley V8, "Normal
Startup of Customized MVS 3.8").

Proves the system as built comes up the ordinary way and goes down
cleanly: IPL from MVSRES without CLPA (IEA101A answered with Enter), IPL
reason U, JES2 warm start, VTAM and TSO started until TSO accepts logons,
then Jay's shutdown. PUB000 and PUB001 come from conf/mvs.cnf now (S4
uncommented them), not from a script.

Jay's optional changes (starting VTAM and TSO from COMMND00, suppressing
IFB010D) are not made: phase 1 builds his system as he describes it.
"""
from ..log import info
from ..mvs import Console

NAME = 's5'
TITLE = 'normal start'

NORMAL_IPL = [
    ('IEA101A', ''),
    ('IFB010D', 'u'),
    ('$HASP426', 'noreq'),
]


def run(ctx):
    with ctx.hercules('conf/mvs.cnf') as herc:
        herc.wait_for(r'HHC00414I 0:0190', 60, since=0, what='Hercules start with PUB001')
        con = Console(herc, ctx.tree, reader='localhost:3505')
        con.ipl('150', NORMAL_IPL)
        since = herc.mark()
        con.command('s net')
        herc.wait_for(r'IKT007I', 300, since=since, what='TSO accepting logons (IKT007I)')
        info('  TSO accepts logons (IKT007I)')
        con.shutdown(before=['p tso', 'z net,quick'])


def verify(ctx):
    for name, volser in (('mvsres.3350', 'MVSRES'), ('mvs000.3350', 'MVS000'),
                         ('spool1.3350', 'SPOOL1'), ('page00.3350', 'PAGE00'),
                         ('pub000.3380', 'PUB000'), ('pub001.3390', 'PUB001'),
                         ('syscpk.3350', 'SYSCPK')):
        ctx.dasd.check(ctx.tree / 'dasd' / name, volser, [])
    info('  all seven volumes of the running system present')
