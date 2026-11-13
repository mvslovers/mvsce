# mvsce — MVS 3.8j sysgen build

Extends `~/repos/mvs/CLAUDE.md`.

Builds an MVS 3.8j system by Jay Moseley's procedure (V8) and adds the
ecosystem's modifications. Successor to the MVS/CE build of
MVS-sysgen/sysgen, but not a fork of its code (no licence upstream).

Status: planning. The design and the open decisions are in
`internals/proposal.md`; read it before any work here.

## Rules specific to this project

- **Every external input goes through `inputs.lock`** (URL, version, size,
  SHA-256). Never `git clone` a HEAD or download a `latest` release in the
  build.
- **No binaries in git**: tapes, DASD images, XMITs are fetched and verified.
- **A stage is done when its manifest holds** (SMP `LIST` of SYSMODs and
  target library members), not when its jobs end with RC 0.
- Products install by SMP from their release packages, as
  `~/repos/mvs/mvs-docker/tk5/setup_tk5.py` does.
- The compatibility contract with MVS/CE 3.0.0 (proposal section 4) is
  binding: a difference is either compatible or a documented change.
- Builds run in throwaway containers (root CLAUDE.md, "Throwaway
  containers"); full sysgens are long runs, so locally, not on `mvsdev`.
- Before adding a usermod or picking an id: `~/repos/mvs/.workspace/context/smp.md`.
