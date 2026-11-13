# mvsce — MVS 3.8j sysgen build

Extends `~/repos/mvs/CLAUDE.md`.

MVS/CE, built new: MVS 3.8j by Jay Moseley's procedure (V8), automated and
reproducible, as an alternative to the MVS/CE build of MVS-sysgen/sysgen.
Green field: no code from upstream (it has no licence), no upstream remote.

Status: phase 1 (the sysgen alone). Design, decisions and what is open:
`internals/proposal.md`; read it before any work here. Nothing beyond Jay's
sysgen goes in before phase 1 is done.

## Rules specific to this project

- **Never mention AI or any AI tool** — not in commits, issues, PRs,
  comments, code, docs or release texts.

- **Every external input goes through `inputs.lock`** (label, URL, size,
  SHA-256). Never `git clone` a HEAD or download a `latest` release in the
  build.
- **No binaries in git**: tapes, DASD images, XMITs are fetched and verified.
- **A stage is done when its manifest holds** (SMP `LIST` of SYSMODs and
  target library members), not when its jobs end with RC 0.
- **Jay's version is a label** in `inputs.lock`, selected in
  `config/sysgen.toml`. Jay replaces his files in place; a hash mismatch
  means a new label, never an edited one. Our changes to Jay's jobs are
  patches under `patches/<label>/`.
- **No automatic retries.** A failure stops the build with its reason.
- Usermods run as Jay's single jobstream; a split needs a measured reason,
  written down.
- Phase 2 (later): products by SMP from their release packages, as
  `~/repos/mvs/mvs-docker/tk5/setup_tk5.py` does, and compatibility with
  MVS/CE 3.0.0 (proposal section 4).
- Builds run in throwaway containers (root CLAUDE.md, "Throwaway
  containers"); full sysgens are long runs, so locally, not on `mvsdev`.
- Before adding a usermod or picking an id: `~/repos/mvs/.workspace/context/smp.md`.
