# mvsce — analysis of the current sysgen and proposal

Status: **accepted in principle** (2026-11-13): new build on Jay's V8, sysgen
first, everything else afterwards. Section 7 records the decisions, section 8
what is still open.

Goal: build an MVS 3.8j system by Jay Moseley's sysgen procedure, and modify
it the way the mvslovers ecosystem needs, in a build that we maintain
ourselves. Until now that system came from
[MVS-sysgen/sysgen](https://github.com/MVS-sysgen/sysgen) (MVS/CE), whose
maintainer has little time.

---

## 1. What exists today

### 1.1 MVS-sysgen/sysgen (MVS/CE)

Analysed at `6672504` (2026-08-01, the v3.0.0 release).

| Item | Finding |
|---|---|
| Base | Jay Moseley's **V7** installation objects (`gz/mvsInstallationResources.tar.gz`, md5 `f1892f1c…`, imported 2021-04-25). Jay has published **V8** since 2024 (objects updated August 2025, md5 `129898e0…`). The starter and distribution tapes are identical in both (md5 `7c12c99c…`, `ec9f1c86…`, checked against Jay's page). |
| Driver | `sysgen.py`, 2954 lines, one class. Starts Hercules as a child process and drives it by matching strings on stdout/stderr (`wait_for_string`), feeding JCL through `devinit` and the socket readers 3505/3506. |
| Flow | 14 steps, 38 DASD checkpoints. Every checkpoint is a full copy of all DASD files (`backup_dasd`/`restore_dasd`). |
| Usermods | 56 usermod jobs in `step_05_usermods`, **one IPL, one job, one shutdown and one full DASD backup each**; `DYNPROC` and `ZP60041` run in later steps. Jay's own procedure applies them in one jobstream. |
| Products | BREXX from a checked-in `xmi/brexx.xmi`; RAKF by `git clone` of `MVS-sysgen/RAKF` **HEAD** plus `rakf-tools.xmit` from the rolling `latest` release; MVP by `git clone` of `MVS-sysgen/MVP` **HEAD**; ISPF, NJE38, UFSD, FTPD, HTTPD, mvsMF, OPNTERSE through MVP (not SMP). Nothing is pinned by version or hash. |
| Success check | `check_maxcc` reads the 1403 printer file for IEF142I/IEF450I. Catches abends since v3.0.0. Nothing checks the SMP inventory, so "the job ran" stands in for "the work happened". |
| Robustness | The documented way to build is `until ./sysgen.py --CONTINUE; do …; done`, because Hercules "may fail". CI runs the same loop. Of the last 12 CI runs, 5 were cancelled after about 6 hours (GitHub's job limit); the successful ones took 38–46 minutes. The last one (2026-10-19, PR #64) shows why: step 8 asks the rolling RAKF `latest` release for `rakf-tools.xmit`, the release had only `install_rakf.jcl`, `sysgen.py` raised, and the `until` loop restarted it **1835 times** in 10-second cycles until GitHub cancelled the job. An unpinned input plus an unconditional retry turns a deterministic error into a six-hour hang. (The other four cancelled runs were not examined.) |
| Hercules | CI builds in `mainframed767/hercules:4.7.0`. The released image carries 4.10.0.11668 (March 2026). Both predate SDL-Hercules-390/hyperion#889 (lost wakeup in the 3215-C console, which can hang an IPL), which our `mvsce` image fixes by building Hyperion at a pinned commit. |
| Platform | Debian/Ubuntu only (README). Issue #62: segfault with a current Hyperion on Ubuntu 24.04 because of `--externalgui`. |
| Repository | 341 MB, 176 MB of it `.git`. Tapes kept twice (`gz/*.tar.gz` and `tape/*.het`), plus `dasd/syscpk.3350`, PDF manuals. **No LICENSE file.** |
| Activity | Commits per year: 253 (2021), 52, 45, 34, 10 (2025), 18 (2026). Our issue #65 ("Asking for 3.1", 2026-11-03) is unanswered; issues from 2022 are open. |

### 1.2 What we already have

- `mvs-docker/mvsce`: an image `FROM mainframed767/mvsce:3.0.0` that replaces
  three things it ships with: Hercules (built at a pinned Hyperion commit with
  the #889 fix), RAKF (removed from SMP and reinstalled as 2.0.0), and the
  product load libraries. It also sets `NUMCPU 1` because two CPUs stalled
  2 of 24 IPLs. Most of that image works around the base.
- `mvs-docker/tk5/setup_tk5.py`: installs UFSD, HTTPD, mvsMF and FTPD **by
  SMP from their release packages** and counts an install only when the
  modules SMP reports as copied (HMA2380) are in the target library. That is
  the model for product installation here.
- `mvsce-target`: throwaway containers for tests; the ecosystem's tests and
  the default mbt target run against MVS/CE 3.0.0.

### 1.3 Jay Moseley V8 compared with V7

V8 objects (`mvsInstallationResources.tar.gz`, md5 `129898e0f0881078448358553bc6b4c1`):

- Builds only from the IBM distribution libraries (V7 took parts from the
  Bekker distribution).
- System data sets can be on 3375/3380/3390; the starter system still needs
  ≤ 3350 for the initial residence volume.
- All usermods in **one** jobstream (`jcl/usermods.jcl`, 7 jobs) from a tape
  (`tape/usermods.het`, created 2025-07-25 by its label).
- Customization installs RPF, QUEUE, REVIEW and DATE from `tape/tsoaps.het`
  (`mvs03.jcl`); V7 had separate review/rpf/queue jobs.

USERMOD ids: V8 from the `SELECT` operands of `usermods.jcl`; MVS/CE from
the `++USERMOD` statements in upstream's `usermods/*.jcl` (ZP60025 is an
EBCDIC file and was checked separately). **Preliminary**: what is in the
JCL, not what is applied; milestone M0 replaces this with an SMP inventory
diff.

| Only in MVS/CE 3.0.0 | In both | Only in V8 |
|---|---|---|
| `SYZJ201`, `SYZJ202`, `ZP60041`–`ZP60043`, `ZUM0007`, `ZUM0008` (and the PTF `UZ61025`) | `#DYP001`–`#DYP005`, `#DYPDMY` (dynamic proclibs; upstream's `DYNPROC.jcl`), `AY12275`, `JLM0001`–`JLM0004`, `SLB0001`, `SLB0002`, `SYZM001`, `TIST801`, `TJES801`, `TMVS804`, `TMVS816`, `TMVS817`, `TNIP800`, `TTSO801`, `VS49603`, `WM00017`, `ZP60001`–`ZP60009`, `ZP60011`–`ZP60022`, `ZP60025`–`ZP60040` | `JLM0005`, `JLM0006` (century fixes), `M096220`, **`MS00100`**, `RP00001`–`RP00003`, `ZP60024`, `ZUM0015` |

Findings that matter for issue #65 (Rob Prins' packages downloaded from
prince-webdesign.nl on 2026-11-13 and read):

- **V8 already carries Rob's MS00100**: V8's tape and Rob's package both say
  `++USERMOD(MS00100) REWORK(20230906)`, with the `(******)` = system
  residence volume change in its history. The receive-once trap from #65
  does not arise on a V8 base.
- V8 has ZP60038 at `REWORK(20190727)` and ZP60017 without a rework; Rob's
  packages are `REWORK(20261106)` and `REWORK(20261108)`. Whether SMP4
  receives a higher rework over an applied SYSMOD is **not verified** — and
  does not need to be: a build from scratch replaces the two members in
  `SYS1.USERMODS` before the first RECEIVE (stage S3), so only Rob's level
  is ever received.
- UY16532 is on V8's `ptfs.het` and is applied (not accepted) by
  `sysgen06.jcl` as a prerequisite of ZP60014 — the same state #65 point 1
  describes for MVS/CE. The `ACCEPT` has to be added either way.
- ZUM0007/ZUM0008 (MVS/CE) and ZUM0015, JLM0005, JLM0006 (V8) are all Y2K or
  century fixes; which set wins is decided by the M0 diff, not by count.

### 1.4 What MVS/CE changed in Jay's V7 jobs

Diff of upstream `jcl/` against V7's (changed lines): `sysgen04` 4845
(parmlib, proclib, logon and VTAM members), `sysgen05` 380, `smpjob03` 184,
`mvs00` 69, `mvs01` 25, `sysgen01` 11 (among them the stage 1 console at
009: 3215 instead of a 3277-2), `sysgen02` 11, `sysgen00` 8. Upstream also
raised VTAM buffer pools and added `vtoc.jcl`, `stage2.jcl` and a
`sysgen05a` template. **This is the porting backlog onto V8**: each change
is either taken over (and listed in the contract, section 4), dropped, or
already in V8.

---

## 2. Options

**A. Fork MVS-sysgen/sysgen and fix it incrementally.** Keeps the V7 base, the
monolithic driver and the MVP installs; most of what we want touches every
part of `sysgen.py`, and upstream has no licence.

**B. New build on Jay's V8 (chosen).** Jay's procedure is the specification.
Upstream's repository is a source of lessons (the cold-start reasoning in
`custjobs_ipl`, the abend check in `check_maxcc`, the EBCDIC submission) and
gets credited; no code is copied. Green field: no upstream remote, no
merging back.

**C. Keep patching the image** (today's `mvs-docker/mvsce`). Every upstream
release has to be re-patched, and SMP history cannot be fixed from outside.

---

## 3. Design

### 3.1 Principles

1. **Every input pinned.** One lockfile, `inputs.lock`, names every external
   input with URL, size and SHA-256 (section 3.2). The build fetches and
   verifies; nothing comes from `HEAD` or `latest`. No binaries in git.
2. **Stages with cached results.** Each stage's output is the compressed DASD
   set, keyed by a hash over its definition, its inputs and the previous
   stage's key. A change rebuilds only from the stage it touches.
3. **The SMP inventory is the result.** Each stage declares what must hold
   afterwards (SYSMODs `APP`/`ACC`, members in target libraries, data sets on
   volumes) and checks it with `LIST` jobs. A return code says the job ran;
   the manifest says the work happened.
4. **Fail fast, no retry loop.** Every wait has a timeout and a reason; on
   timeout the build stops with the console tail, the printer tail and the
   stage name. No automatic retry. A problem that recurs gets found and
   fixed, not repeated.
5. **Configuration as data.** Users, volumes, device addresses, ports and the
   release identity live in TOML, not in the driver.
6. **Small steps.** Phase 1 is the sysgen alone. Nothing is added on top
   until it runs automated and reliably (section 3.3).

### 3.2 Which version of Jay's sysgen

Jay publishes his objects under fixed URLs and replaces the files in place
(`mvsInstallationResources.tar.gz` was last updated in August 2025; the name
carries no version). A pin by URL alone would silently change the build. So:

- `inputs.lock` has one entry per archive with a **label** of our choosing
  (`jay-v8-2025-08`), the URL, size and SHA-256. The page's md5 is recorded
  too, as the cross-check against Jay's own statement.
- `config/sysgen.toml` selects the label to build with (`jay = "jay-v8-2025-08"`).
  A new label means a new entry; old labels stay, so an old release can be
  rebuilt.
- The fetch fails with a clear message when Jay's file no longer matches
  ("Jay has published new objects: add a new label"), never with a broken
  build halfway through.
- Every archive we have built with is kept in a build cache (GitHub Actions
  cache, local `cache/`), so a rebuild does not depend on the file still
  being on Jay's site. Whether we also publish copies is part of the licence
  question (section 8).
- A scheduled CI job compares Jay's files with the lock once a week and opens
  an issue when they change.

Our own changes to Jay's jobs are patches applied on top of the selected
label (`patches/<label>/…`), so a new Jay version shows exactly which of them
still apply.

### 3.3 Phases and stages

**Phase 1 — the sysgen (now).** Jay V8, chapters 2 to 5, automated:

| Stage | Content | Jay V8 |
|---|---|---|
| S1 starter | MVS 3.7 starter system | chapter 2 |
| S2 dlibs | SMP4, distribution libraries | chapter 3 |
| S3 sysgen | Stage 1/2, JES2, PTFs (`sysgen06`), **usermods as Jay's one jobstream** (`usermods.jcl`), ICKDSF R13 | chapter 4 |
| S4 base | PUB000/PUB001, catalogs, SYSCPK, RPF/QUEUE/REVIEW/DATE, TSO users | chapter 5 |
| S5 finalize | Clean shutdown, warm-startable system, release identity, verification | chapter 6 |

The usermods run as Jay ships them, in one jobstream. Upstream applied them
one IPL at a time because of past sysgen problems; we start with the single
jobstream and find out ourselves whether, and where, that breaks. If a
usermod needs a separate IPL, the stage splits there and the reason is
written down.

**Phase 2 — everything on top (later, discussed when phase 1 runs).**
Default: everything MVS/CE 3.0.0 ships today, in current versions where
possible, plus the ecosystem's products and SDSF, plus the content of issue
#65. Known points for that discussion:

- RAKF in its current version (2.0.0, by SMP);
- BREXX/370 3.1.0 + ZMG0001 (with `ACCEPT UY16532`), replacing the old
  BREXX;
- MVP is built on an old BREXX; it is to be replaced by a native tool, so
  package management is a topic of its own;
- UFSD, FTPD, HTTPD, mvsMF, SDSF by SMP from their releases;
- Rob Prins' ZP60038/ZP60017 reworks (they replace the V8 members before
  S3, see 1.3), `SYS1.CMDLIB` sizing;
- ISPF, NJE38, RPF and the rest of today's MVS/CE contents.

### 3.4 Driver

Python 3, standard library only, small modules instead of one class:
Hercules process and console, card reader submit (ASCII/EBCDIC), job-result
parser (the printer file, including abends), SMP inventory checker, stage
runner, cache. One printer file per stage, emptied at its start. Runs in a
container with Hercules built at a pinned Hyperion commit, as
`mvs-docker/mvsce` already does, so it works the same on macOS (Docker or
Apple `container`), on `mvsdev` and in GitHub Actions.

### 3.5 Outputs

- Release tarball: DASD (CCKD), Hercules configuration, start script,
  `MANIFEST` (Jay label, component versions, SMP inventory, SHA-256 of every
  DASD file).
- Later: an OCI image built from that tarball, which `mvs-docker/mvsce` then
  uses as its base.
- `SYS1.PARMLIB(RELEASE)` carries the version and the git commit.

### 3.6 Tests

- Per stage: the declared SMP/data set manifest.
- After S5: IPL, JES2 warm start, TSO logon (`mbt target ping --tso`).
- Reproducibility: two builds from the same commit give the same SMP
  inventory.
- Phase 2 adds `mbt test --mvs` of the installed products.

---

## 4. Compatibility with MVS/CE 3.0.0

The ecosystem's tests, the mbt default target and the `mvsce` image assume
MVS/CE 3.0.0. Before phase 2, the unmodified `mainframed767/mvsce:3.0.0`
image is measured: volume serials and device addresses, users, ports, JES2
classes and MSGCLASS conventions, SVC slots (MVS/CE: 240–255), the complete
SMP inventory, proclib behaviour, LNKLST and APF list, and upstream's changes
to Jay's jobs (1.4). Each difference is either made compatible or listed as
a deliberate change. Phase 1 builds Jay's system as Jay describes it.

---

## 5. Milestones

| | Content | Done when |
|---|---|---|
| M1 | Repository, lockfile with Jay label, container, driver skeleton; S1 | starter system built in CI |
| M2 | S2–S3 (usermods in one jobstream) | SMP inventory of S3 matches the manifest |
| M3 | S4–S5, stage cache | two builds, identical SMP inventory; TSO logon |
| M4 | CI: build on push, release tarball, weekly Jay check | release `v0.1.0` (Jay's system, automated) |
| — | Phase 2 planning: scope, package management, MVS/CE 3.0.0 baseline | discussed with the maintainer |

---

## 6. Repository layout (planned)

```
mvsce/
  inputs.lock          every external input: label, url, size, sha256
  config/              sysgen.toml (Jay label), users.toml, volumes.toml
  patches/<label>/     our changes to Jay's jobs, per Jay version
  driver/mvsce/        Python package: inputs, hercules, dasd, build (cache)
  driver/mvsce/stages/ one module per stage: run(), verify() = its manifest
  sysgen               entry point
  container/           Dockerfile for the build environment
  docs/                user documentation
  internals/           this file, measurements, releasing.md
```

---

## 7. Decisions (2026-11-13)

1. **New build**, green field, no upstream remote. The maintainer will show
   the result to the MVS/CE maintainer later; whether it continues in his
   repository or in this one is decided then.
2. **Name: MVS/CE.** It is meant as an alternative for MVS/CE, not a new
   product. Repository `mvslovers/mvsce`, public.
3. **Sysgen first.** Phase 1 is Jay's sysgen automated; everything else is
   discussed afterwards (section 3.3).
4. **Usermods in one jobstream**, as Jay ships them; problems are found and
   fixed ourselves.
5. **Default scope of phase 2**: everything MVS/CE ships today, in current
   versions where possible, plus the ecosystem's products, SDSF and issue #65.
6. **Upstream's Docker repository is ignored**; `mvs-docker/mvsce` switches to
   this build later.

## 8. Open

1. **Licence** of this repository and redistribution of Jay's objects and the
   usermods. Fetching from Jay's site is unproblematic; publishing copies
   (for reproducibility) needs clarification. Postponed.
2. **Package management** (successor to MVP). Phase 2.
3. **Further own changes** beyond #65 (TSO/JES2 defaults, volume layout, 3390
   residence). Phase 2.
