# Compatibility with MVS/CE 3.0.0

Phase 2 makes this build a drop-in replacement for MVS/CE 3.0.0. A user,
a job, a script or an image built on top of MVS/CE 3.0.0 must keep working
when it runs on this build instead. Every difference is deliberate and is
listed here, in **Deliberate differences**; anything else that differs is a
bug.

## How it is measured

The reference is the release archive of MVS/CE 3.0.0 (`DISTRIB_DATE
08/01/26`, `SYS1.PARMLIB(RELEASE)`), unpacked, with its configuration
`conf/local.cnf`. Its inventory is in `baseline/mvsce-3.0.0/`, written by

    ./sysgen inventory --system MVSCE --config conf/local.cnf \
        --out internals/baseline/mvsce-3.0.0

The inventory reads DASD images and the Hercules configuration, without an
IPL: devices, volumes, data sets (DSORG, RECFM, LRECL, BLKSIZE, tracks,
extents), the members of every partitioned data set (size and hash, or names
only for load libraries), and the text of the configuration libraries
(PARMLIB, PROCLIBs, CMDPROCs, VTAMLST, SECURE.CNTL, EXEC, CLIST, CONTROL,
UMODCNTL). Every layer's release is compared against it:

    ./sysgen inventory --system dist/mvsce-X --config conf/mvs.cnf --out inv
    ./sysgen inventory-diff internals/baseline/mvsce-3.0.0 inv \
        --labels "MVS/CE 3.0.0" "X" --out report.md

The SMP inventory of the baseline (APPLY/ACCEPT status per SYSMOD) needs
an IPL and is not in the baseline yet; `SYS1.SMPPTS` gives the received
SYSMODs.

`baseline/mvsce-3.0.0/text/SYS1.SECURE.CNTL@MVS000/USERS` holds the RAKF
users of MVS/CE with their passwords. They are the public defaults of the
MVS/CE release and are documented there.

## The contract

What a user of MVS/CE 3.0.0 relies on. The status column is the state of
v0.1.0 (the sysgen only, phase 1).

| Area | MVS/CE 3.0.0 | v0.1.0 | Layer |
|---|---|---|---|
| CPU, storage | NUMCPU 2, MAINSIZE 16 | NUMCPU 1, MAINSIZE 8 | P2.4 |
| Code page | `CODEPAGE 819/1047` | Hercules default | P2.4 |
| Volumes, addresses | MVSRES 150, MVS000 151, PAGE00 152, SPOOL1 153, PUB000 180 (3380), PUB001 190 (3390), SMP000 250, WORK00 251, WORK01 252, SYSCPK 253 | the same | – |
| Sort work | SORTW1–6, 2314, 220–225 | none | open (D3) |
| Readers | 00C ASCII socket 3505, 01A EBCDIC socket 3506, 01C | 00C socket 3505, 01C | P2.4 |
| Consoles | 010 3270 master, 009 3215-C, 015 hardcopy | the same | – |
| TSO terminals | 0400.32, 31 active in VTAM (LCL400, APPLTSO) | 0400.8 group `tso` | open (D5) |
| NJE | 0602 TCPNJE 2703, NJE38 | none | P2.3 |
| System id | SMF `SID=MVSC` | `SID=HMVS` | P2.1 |
| Users | IBMUSER, MVSCE01, MVSCE02 (CLIST, CNTL, EXEC, LOAD, SOURCE, UFSHOME) | HMVS01, HMVS02 (no EXEC, no UFSHOME) | open (D2) |
| Security | RAKF 2.0.0, `SYS1.SECURE.*`, RAKF procedures | none | P2.1 |
| REXX | BREXX/370 2.5.3 (`BREXX.V2R5M3.*`, `SYS2.LINKLIB(BREXX)`), RX procedures | none | P2.1 |
| Products | UFSD, FTPD, HTTPD (`MVSLOVER.*`, `HTTPD.*`, `UFSD.*`) | none | P2.2 |
| ISPF, REVIEW, NJE38, MVP | installed | none (RPF instead) | P2.3 / P2.5 |
| SYSCPK | MVS/CE's older SYSCPK | Jay's SYSCPK of Feb 2026 | open (D1) |
| JES2 | MAXJOBS 1024, NUMJOES 3000, two readers, `START JES2,,,PARM='WARM,NOREQ'` | Jay's values | P2.4 |
| VTAM | `START NET` in COMMND00, larger buffer pools (ATCSTR00) | started by the build | P2.4 |
| LNKLST | `SYS2.CMDLIB` last, no SYSC.LINKLIB | `SYSC.LINKLIB` added (Jay) | P2.1 (MS00100) |
| APF | `SYSGEN.NJE38.AUTHLIB` added | – | P2.3 |

## Work list by layer

### P2.1 security and REXX (0.2.0)

- RAKF 2.0.0 by SMP; `SYS1.SECURE.CNTL(USERS, PROFILES)`, `SYS1.SECURE.PWUP`,
  `SYS1.SECURE.SHADOW`, `SYS1.PARMLIB(RAKFINIT)`, procedures RAKF, RAKFPROF,
  RAKFPWUP, RAKFUSER, RACIND; LPALIB ICHRIN00, ICHSFR00; LINKLIB RAKF*.
- BREXX/370 3.1.0 with ZMG0001 instead of 2.5.3; procedures RXBATCH, RXTSO,
  RX2ASM; `SYS2.EXEC`.
- ACCEPT UY16532; LNKLST through MS00100 (already applied in v0.1.0).
- `SYS1.PARMLIB(RELEASE)` with the MVS/CE fields (`DISTRIB_ID` …), for
  scripts that read it.
- SMF system id `MVSC`.

### P2.2 our products by SMP (0.3.0)

- UFSD, FTPD, HTTPD, mvsMF, SDSF by SMP, the procedures UFSD, UFSDCLNP,
  FTPD, HTTPD in `SYS2.PROCLIB`, `UFSD.ROOT`, `UFSD.SCRATCH`, `HTTPD.WEBROOT`,
  `<user>.UFSHOME`.
- MVS/CE ships them as `MVSLOVER.UFSD.LOADLIB`, `MVSLOVER.FTPD.LOADLIB`,
  `HTTPD.LINKLIB`; SMP installs put them into `<PROD>.LINKLIB`. The library
  names are a deliberate difference; the procedure names stay.

### P2.3 the rest of MVS/CE (0.4.0)

- NJE38 (`SYSGEN.NJE38.*`, 0602 TCPNJE, APF, NETSPOOL), ISPF
  (`SYSGEN.ISPF.*`, `SYS1.CMDPROC(ISPF, C$ISPOP5)`), REVIEW
  (`SYSGEN.REVIEW.*`), GCCISP5, ACE*, AMATERSE, GETDTE, `SYS2.CMDLIB` tools
  (ADDUSER, ALTUSER, CDSCB, CHKDSN, COMPARE, FINDMEM, …) with `SYS2.HELP`.
- `SYS2.JCLLIB`, `SYS2.MACLIB`, `SYS2.PARMLIB`, `SYS2.SAMPLIB`, `SYS2.CMDPROC`.
- Usermods only in MVS/CE: NJE0001, RAK0001, SYZJ201, SYZJ202, ZJW0003,
  ZJW0004, ZUM0007, ZUM0008 (see D4).
- ZP60038/ZP60017 reworks from issue #65.
- The shutdown commands SHUTDOWN and SHUTFAST (CMDPROC, EXEC, PROCLIB).

### P2.4 operation (along the way)

- Hercules configuration: NUMCPU, MAINSIZE, CODEPAGE, the second reader,
  the punch and printer directories.
- JES2PM00, COMMND00, ATCSTR00, IKJACCNT (DYNAMNBR 64, SYS2.CMDPROC),
  TSONUSER (SIZE 8192, EXEC data set), STDLOGON text, SETPFK00, the ASMFC*
  procedures (MAC2/MAC3, SOUT).

## Deliberate differences

Kept on purpose; each says why.

| Difference | Why |
|---|---|
| Usermods JLM0005, JLM0006, M096220, MS00100, RP00001–3, ZP60024, ZUM0015 present | Jay V8 applies them; MVS/CE 3.0.0 does not have them |
| RPF installed | part of Jay V8's customisation |
| Products in `<PROD>.LINKLIB` instead of `MVSLOVER.*` | SMP installs (ecosystem rule) |
| BREXX/370 3.1.0 instead of 2.5.3 | newer version |
| JES2 checkpoint 10 s (patch 0003) | shutdown time |
| PCI fix in Hercules | lost print lines otherwise |

## Open decisions

- **D1 SYSCPK.** MVS/CE's older SYSCPK (283 SYSC.LINKLIB members only
  there, BASIC360, an older SORT) or Jay's of February 2026 (Pascal, SIMULA,
  SPITBOL, BASIC 370 extra). A job that calls a member only in the old one
  breaks.
- **D2 users.** HMVS01/HMVS02 from Jay, or MVSCE01/MVSCE02 and IBMUSER with
  the MVS/CE data sets. Scripts written for MVS/CE log on as MVSCE01.
- **D3 SORTW1–6.** Six 2314 sort work volumes at 220–225.
- **D4 MVS/CE-only usermods.** NJE0001, RAK0001, SYZJ201/202, ZJW0003/4,
  ZUM0007/8: take over, replace by a newer equivalent, or drop.
- **D5 device generation.** MVS/CE's stage 1 differs (SYS1.AGENLIB,
  SYS1.OBJPDS01–03 members differ, 0400.32 terminals). 1:1 here means a
  patch to Jay's SYSGEN00 stage 1 deck, not a later layer.
