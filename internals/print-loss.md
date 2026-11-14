# Lost print lines on the starter system: a duplicate PCI in Hercules

Issue #7. Measured 2026-11-13/14.

## Symptom

On the MVS 3.7 starter system (JES2 4.0, "HASP-II, VERSION JES2 4.0"),
printed job output on the 1403 at 00E sometimes misses whole blocks of
**exactly 24 lines**. In S3 this once removed the `IEF142I` of one
USERMODS step, and the build stopped with "158 steps ran, expected 159".
The work itself was done; only output was lost.

The generated MVS 3.8j (JES2 4.1) did not show it in 150 test jobs, also
under load.

## Reproduction

A stress test on the starter system (S1 result), several Hercules
instances in parallel, per round two jobs:

- A: IEBGENER of 20,000 numbered cards to `SYSOUT=A`; every number must
  appear once in `prt00e.txt`;
- B: 200 IEFBR14 steps with a temporary data set each; every step must
  show its `IEF142I`.

| Hercules | environment | A without loss | B without loss |
|---|---|---|---|
| 4.10.0.11800 (`ga29f6c48`, local build) | macOS, one instance | 23 / 25 | 25 / 25 |
| same | macOS, four in parallel | 16 / 100 | 96 / 100 |
| 4.7.0, 4.9.1, `ga7423980` | Apple `container`, 1-8 CPUs | 0 (every third block lost) | 0 |
| `ga7423980` (the CI commit), built natively | macOS, four in parallel | **0 / 100** | 89 / 100 |
| `ga7423980` without the duplicate PCI (below) | macOS, four in parallel | **100 / 100** | **100 / 100** |
| develop `g5648e0e7`, built natively | macOS, four in parallel | **0 / 100** | 92 / 100 |
| develop `g5648e0e7` without the duplicate PCI | macOS, four in parallel | **100 / 100** | **100 / 100** |

With the fix on develop, the whole build S1-S5 ran green as a regression
test (DASD, tape, card reader I/O, both JES2 versions, SMP 126/126).

Every gap was a multiple of 24 lines (210 gaps of exactly 24 in one
series). Setting `&PRTBOPT=NO` in the starter's `SYS1.PARMLIB(JES2PARM)`
reduced but did not remove the loss; JES2 4.0 kept using PCI.

## What happens

With `t+00e` (CCW trace of the printer) the missing lines are never sent:
the channel program itself skips them. JES2 prints in groups of 24 write
CCWs separated by NOPs and extends the running chain on PCI (program
controlled interruption) interrupts: each PCI tells it the channel has
moved on, so it frees the group behind and builds the next one.

At every gap Hercules presents **the same PCI twice**: two CSWs with
status X'0080' and the same CCW address, no PCI-flagged CCW executed in
between. JES2 4.0 counts the second as one more group done, starts the
next channel program one group too far, and the 24 lines in between are
never printed.

## Cause in Hercules

`channel.c` (Hyperion, unchanged since commit `accb0fc0`, "Channel
cleanup (Phase I)", 2013) raises the PCI of a write CCW twice:

1. when the CCW is fetched (`if (flags & CCW_FLAGS_PCI) raise_pci(...)`,
   about line 5041);
2. after its execution, because every write CCW enters the prefetch
   table with its flags, and the prefetch loop "raises requested PCI
   interrupts" for each entry again (about line 5657).

`raise_pci` replaces a PCI not yet presented. Whether the guest sees one
interrupt or two therefore depends on whether the CPU takes the first
before the channel raises the second: timing, host load, emulation
environment. That is why the rate ranged from rare to every third block.

Every fetched CCW, data-chained prefetch entries included, passes the
fetch-time check (only TICs and CCWs failing at fetch do not), so the
second raise is always a duplicate. Removing it (one place, four lines)
ends the loss completely in the measurements above.

## A second finding on the way

The CI image's Hercules `a742398` predates Hyperion #893 ("con1052c.c:
queue console input until the guest has read it"). With it, the empty
reply to IEA101A went once to a console that was not reading yet
(`HHC00010A Enter '/' input` came after the input) and was lost; the
IPL waited for ever. The build's earlier green runs on `a742398` got
through by timing. Hyperion develop has #893.

## Consequences for this build

- The build already fails loudly on such a loss (step and job counts),
  never silently.
- The fix belongs in Hercules. Until it is there, the build can pin a
  Hercules commit that carries it (`HERCULES_REPO`/`HERCULES_REF` in
  `container/Dockerfile`), on top of a develop that has #893.
- The loss grows with the amount of printed output, so a long jobstream
  such as Jay's USERMODS is the most exposed. Whether this is the
  "problem with the sysgen" that led upstream MVS/CE to apply the
  usermods one IPL at a time is not known; it would fit.
