# mvsce

A reproducible build of MVS 3.8j on Hercules, following Jay Moseley's sysgen
procedure, automated and reproducible: an alternative build of MVS/CE.

**Status:** phase 1, automating the sysgen. Jay Moseley's whole procedure
runs automated, about twelve minutes on a laptop: S1 starter system, S2
SMP4 and the distribution libraries, S3 system generation, PTFs, usermods
and ICKDSF, S4 the first IPL and customisation of the new system, S5 a
normal start with TSO accepting logons. Releases are next; the plan is in
[`internals/proposal.md`](internals/proposal.md).

## Building

Needs Hercules (SDL Hyperion, with `dasdinit` and `dasdls`) and Python 3.11
or later, nothing else. Or use the build environment in `container/`.

```sh
./sysgen stages                 # list the stages
./sysgen fetch                  # fetch and verify Jay Moseley's objects
./sysgen build                  # build all stages
./sysgen build --until s1       # up to a stage
./sysgen build --no-cache       # run every stage again
./sysgen build --from s2        # start at a stage, on the last result of the
                                # one before (for development; caches nothing)
./sysgen build --record         # measure: report differing condition codes
                                # instead of stopping (still fails at the end)
```

Inputs and stage results are cached in `cache/`, the build tree and the
Hercules logs are in `build/`. Which version of Jay Moseley's objects is
used is set in `config/sysgen.toml`; the files themselves, with their
checksums, are listed in `inputs.lock`.

In the container:

```sh
docker build -t mvsce-build container
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/src" -w /src mvsce-build ./sysgen build
```

## Credits

- Jay Moseley, whose installation procedure and objects this build follows:
  <https://www.jaymoseley.com/hercules/>
- MVS/CE ([MVS-sysgen/sysgen](https://github.com/MVS-sysgen/sysgen)), the
  automated build this project learned from.
- The authors of the usermods applied here (Greg Price, Rob Prins, Jay
  Moseley and others).
