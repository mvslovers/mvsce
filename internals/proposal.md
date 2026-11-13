# mvsce — analysis of the current sysgen and proposal

Status: **proposal, not decided** (2026-11-13). Section 7 lists the decisions
that are open.

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
| Usermods | 58 usermods, **one IPL, one job, one shutdown and one full DASD backup each** (`step_05_usermods`). Jay's own procedure applies them in one jobstream. |
| Products | BREXX from a checked-in `xmi/brexx.xmi`; RAKF by `git clone` of `MVS-sysgen/RAKF` **HEAD** plus `rakf-tools.xmit` from the rolling `latest` release; MVP by `git clone` of `MVS-sysgen/MVP` **HEAD**; ISPF, NJE38, UFSD, FTPD, HTTPD, mvsMF, OPNTERSE through MVP (not SMP). Nothing is pinned by version or hash. |
| Success check | `check_maxcc` reads the 1403 printer file for IEF142I/IEF450I. Catches abends since v3.0.0. Nothing checks the SMP inventory, so "the job ran" stands in for "the work happened". |
| Robustness | The documented way to build is `until ./sysgen.py --CONTINUE; do …; done`, because Hercules "may fail". CI runs the same loop. Of the last 12 CI runs, 5 were cancelled after about 6 hours (GitHub's job limit); the successful ones took 38–46 minutes. |
| Hercules | CI builds in `mainframed767/hercules:4.7.0`. The released image carries 4.10.0.11668 (March 2026). Both predate SDL-Hercules-390/hyperion#889 (lost wakeup in the 3215-C console, which can hang an IPL). **Hypothesis, not measured:** the 6-hour hangs are that bug. |
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

Usermods in V8's `usermods.jcl` (`SELECT` operands), compared with
`sysgen.py`'s list. **Preliminary**: taken from the JCL and the extracted
tape; milestone M0 replaces this with an SMP inventory diff.

| Only in MVS/CE 3.0.0 | In both | Only in V8 |
|---|---|---|
| `DYNPROC` (dynamic proclibs), `SYZJ2001`, `UZ61025`, `ZUM0007`, `ZUM0008`, `ZP60041`–`ZP60043` | `AY12275`, `JLM0001`–`JLM0004`, `SLB0001`, `SLB0002`, `SYZM001`, `TIST801`, `TJES801`, `TMVS804`, `TMVS816`, `TNIP800`, `TTSO801`, `VS49603`, `WM00017`, `ZP60001`–`ZP60009`, `ZP60011`–`ZP60022`, `ZP60025`–`ZP60039` | `#DYP001`–`#DYP005`, `#DYPDMY` (dynamic proclibs, other implementation), `JLM0005`, `JLM0006`, `M096220`, **`MS00100`**, `RP00001`–`RP00003`, `TMVS817`, `ZP60024`, `ZP60040`, `ZUM0015` |

Three findings that matter for issue #65:

- **V8 already carries Rob Prins' MS00100**: `++USERMOD(MS00100)
  REWORK(20230906)`, with the `(******)` = system residence volume rework in
  its history. The receive-once trap from #65 does not arise on a V8 base.
- V8's ZP60038 is `REWORK(20190727)` and ZP60017 the original. Rob's
  November 2026 reworks of both carry later rework dates, so SMP accepts them
  over the V8 level (to be confirmed in M2).
- Dynamic proclibs differ (`DYNPROC` vs. `#DYP…`). Anything in the ecosystem
  that relies on MVS/CE's proclib behaviour must be checked against the
  `#DYP` implementation.

---

## 2. Options

**A. Fork MVS-sysgen/sysgen and fix it incrementally.** Keeps the history and
stays mergeable with upstream. But it keeps the V7 base, the monolithic driver
and the MVP installs, and most of what we want (pinning, SMP installs, V8,
batched usermods, verification) touches every part of `sysgen.py`. Without a
licence a fork is also legally open.

**B. New build on Jay's V8, with MVS/CE as the reference (recommended).** Jay's
procedure is the specification; upstream's repository is a source of lessons
(the cold-start reasoning in `custjobs_ipl`, the abend check in
`check_maxcc`, the RAKF EBCDIC submission) and gets credited. Compatibility
with what the ecosystem runs on today is kept by an explicit contract
(section 4), not by sharing code.

**C. Keep patching the image** (today's `mvs-docker/mvsce`). Cheapest now, but
every upstream release has to be re-patched, and SMP history (old RAKF,
missing UY16532 accept, products outside SMP) cannot be fixed from outside.

---

## 3. Proposed design (option B)

### 3.1 Principles

1. **Every input pinned.** One lockfile, `inputs.lock`, names every external
   input with URL, version, size and SHA-256: Jay's three archives, SYSCPK,
   RAKF, BREXX/370 + ZMG0001, UY16532, Rob's usermods, our product packages.
   The build fetches and verifies; nothing comes from `HEAD` or `latest`.
   Large binaries are not in git.
2. **Stages with cached results.** The build is a chain of stages; each
   stage's output is the compressed DASD set, keyed by a hash over its
   definition, its inputs and the previous stage's key. Changing a product
   rebuilds only the last stages (minutes, not an hour).
3. **The SMP inventory is the result.** Each stage declares what must hold
   afterwards (SYSMODs `APP`/`ACC`, members in target libraries, data sets on
   volumes) and checks it with `LIST` jobs. A return code says the job ran;
   the manifest says the work happened.
4. **Fail fast, no retry loop.** Every wait has a timeout and a reason; on
   timeout the build stops with the console tail, the printer tail and the
   stage name. A retry is an explicit, logged decision per IPL, at most once.
5. **Products by SMP from their releases**, as `setup_tk5.py` does, never by
   copying load modules.
6. **Configuration as data.** Users, RAKF profiles, volumes, device
   addresses, ports and the release identity live in TOML, not in the driver.

### 3.2 Stages

| Stage | Content | Source |
|---|---|---|
| S1 starter | MVS 3.7 starter system | Jay V8, chapter 2 |
| S2 dlibs | SMP4, distribution libraries | Jay V8, chapter 3 |
| S3 sysgen | Stage 1/2, JES2, usermods (one jobstream), ICKDSF R13 | Jay V8, chapter 4 |
| S4 base | Volumes PUB000/PUB001, catalogs, SYSCPK, RPF/QUEUE/REVIEW/DATE, TSO users | Jay V8, chapter 5 |
| S5 platform | RAKF 2.0.0 (SMP), `ACCEPT UY16532`, BREXX/370 3.1.0 (TBRX310) + ZMG0001, LNKLST via MS00100 | #65 points 1, 3, 4 |
| S6 mods | Rob's ZP60038 and ZP60017 reworks, further usermods, sizing (e.g. `SYS1.CMDLIB`, 93 % full on MVS/CE 3.0.0) | #65 points 5, 6 |
| S7 products | UFSD, FTPD, HTTPD, mvsMF by SMP, procedures, parmlib, autostart | #65 point 2 |
| S8 extras | ISPF, NJE38, MVP — each optional | upstream steps 9–12 |
| S9 finalize | COMMND00, shutdown procedures, release identity, clean warm start, full verification | upstream step 14 |

S1–S4 change rarely; their cached output is what makes the rest fast.

### 3.3 Driver

Python 3, no dependencies outside the standard library, small modules instead
of one class: Hercules process and console, card reader submit (ASCII/EBCDIC),
job-result parser (the printer file, including abends), SMP inventory checker,
stage runner, cache. One printer file per stage, emptied at its start, so a
job's output is never confused with a previous stage's. Runs in the pinned
Hercules container (`ghcr.io/mvslovers/hercules` at the Hyperion commit the
`mvsce` image already uses), so it works the same on macOS (Docker or Apple
`container`), on `mvsdev` and in GitHub Actions.

### 3.4 Outputs

- Release tarball: DASD (CCKD), Hercules configuration, start script,
  `MANIFEST` (component versions, SMP inventory, SHA-256 of every DASD file).
- OCI image `ghcr.io/mvslovers/mvsce` built from that tarball.
  `mvs-docker/mvsce` then drops the Hercules replacement, the RAKF swap and
  the load-library patching.
- `SYS1.PARMLIB(RELEASE)` carries the version and the git commit.

### 3.5 Tests

- Per stage: the declared SMP/data set manifest.
- Smoke test after S9: IPL, JES2 warm start, TSO logon (`mbt target ping
  --tso`), RAKF login, the STCs up.
- Acceptance: `mbt test --mvs` of UFSD, FTPD, HTTPD, mvsMF and BREXX/370
  against the built system in a throwaway container.
- Reproducibility: two builds from the same commit give the same SMP
  inventory.

---

## 4. Compatibility contract with MVS/CE 3.0.0

The ecosystem's tests, the mbt default target and the `mvsce` image assume
MVS/CE 3.0.0. Before anything changes, milestone M0 measures and writes down:

- volume serials and device addresses (`conf/local.cnf`: MVSRES, MVS000,
  PAGE00, SPOOL1, PUB000, PUB001, SYSCPK, SMP000, WORK00, WORK01, sort
  volumes), device types;
- users and passwords (IBMUSER, MVSCE01, MVSCE02), RAKF groups and profiles;
- ports (3270, 3505 ASCII, 3506 EBCDIC, 8888 Hercules HTTP);
- JES2 classes and initiators, MSGCLASS conventions (`mvsce` image: class A,
  msgclass H, volume WORK00);
- SVC slots in use (MVS/CE: 240–255; registry in `svc.md`);
- the complete SMP inventory (CDS and ACDS);
- proclib behaviour (`DYNPROC` vs. `#DYP`), LNKLST, APF list.

Each difference between that baseline and the new build is either kept
compatible or listed as a deliberate change in the release notes.

---

## 5. Milestones

| | Content | Done when |
|---|---|---|
| M0 | Baseline: run upstream v3.0.0 in our pinned container (time, hangs: tests the #889 hypothesis), extract inventory and configuration | contract (section 4) written; hang hypothesis measured |
| M1 | Lockfile, driver, cache; S1–S3 from V8 | two builds, identical SMP inventory |
| M2 | S4–S5 | RAKF, BREXX/370 3.1.0, ZMG0001 verified; UY16532 `ACC` |
| M3 | S6–S7 | all of #65 in; diff against M0 resolved |
| M4 | S8–S9, CI, release, OCI image; `mvs-docker/mvsce` switches its base | `mbt test --mvs` green for all products on the new image |
| M5 | Documentation (`docs/`), release page, announcement | — |

---

## 6. Repository layout (planned)

```
mvsce/
  inputs.lock          every external input: url, version, size, sha256
  config/              users.toml, rakf-profiles, volumes.toml, release.toml
  stages/s1-starter/   stage.toml (devices, jobs, expected CCs, manifest) + JCL
  ...
  stages/s9-finalize/
  usermods/            our own and third-party usermods not on Jay's tape
  driver/              Python package (hercules, reader, jobs, smp, cache)
  container/           Dockerfile for build environment and runtime image
  docs/                user documentation
  internals/           this file, measurements, releasing.md
```

---

## 7. Open decisions

1. **Name.** "MVS/CE" (MVS Community Edition) is upstream's product name and
   `mainframed767/mvsce` its image. Using the same name for a different build
   invites confusion in both directions. Options: agree with the upstream
   maintainer that this becomes the continuation of MVS/CE, or keep the repo
   name `mvsce` and give the product its own name.
2. **Licence and redistribution.** Upstream has no LICENSE, so its code cannot
   be copied without permission; option B avoids copying it. Jay Moseley's
   objects and the usermods (Greg Price, Rob Prins, Jay, others) are
   redistributed by many projects, but terms should be confirmed — at least
   whether we fetch them from the original sites (pinned by hash) or mirror
   them as release assets.
3. **Scope of S8.** Which of ISPF (Wally), NJE38, MVP, RPF, KICKS belong in
   the default system.
4. **Relation to upstream.** Offer the changes back (issue #65 stays the
   channel) or continue independently.
5. **Project registration.** GitHub repository `mvslovers/mvsce`, entry in the
   root `CLAUDE.md` project list and in `status.md`.
