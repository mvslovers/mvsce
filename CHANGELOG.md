# Changelog

## 0.1.0

First release: MVS 3.8j built by Jay Moseley's installation procedure
(guide V8, installation objects of August 2025), fully automated.

- The whole procedure runs without operator input: the MVS 3.7 starter
  system, SMP4 and the distribution libraries, the system generation with
  Jay's PTFs and usermods (as his single jobstream), ICKDSF R13, the first
  IPL and customisation of the new system, and a normal restart.
- Every job is checked against the condition codes Jay gives, and the
  target zone's SMP inventory against what his jobs apply and accept.
- Every input is pinned by SHA-256; Jay's files are selected by a label.
- Three changes to Jay's files: the console of the starter configurations
  and console 009 of the new system are Hercules' integrated 3215-C, and
  JES2 checkpoints every 10 seconds instead of 60, so a shutdown takes
  about 15 seconds instead of a minute.
- The release package holds the ten volumes of the running system as
  compressed CCKD images (about 110 MB), the Hercules configuration, a
  start script and a manifest of everything that went into it.
