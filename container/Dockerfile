# Build environment: Hercules (SDL Hyperion at a pinned commit) and Python.
#
# HERCULES_REF is Hyperion develop (5648e0e7, with the 3215-C console fixes
# #889 and #893 and the X'75' TCP/IP fixes) plus the fix for PCI raised
# twice (SDL-Hercules-390/hyperion#906, PR #907), on the mvslovers fork
# until it is merged: without it JES2 4.0 on the starter system loses
# blocks of 24 print lines (internals/print-loss.md). hercules-helper is
# pinned as well. Built with a portable -O3 instead of hercules-helper's
# -march=native, which would SIGILL on a host whose CPU lacks the build
# machine's instructions.

ARG HERCULES_REF=34c1bc40e534381bf77c474c5bb37520104fe2b6
ARG HERCULES_REPO=https://github.com/mvslovers/hyperion.git
ARG HELPER_REF=6b981ba2fbde86c7146e46608797d8c85c1835d3

FROM debian:trixie AS hercules

ARG HERCULES_REF
ARG HERCULES_REPO
ARG HELPER_REF

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       sudo time git curl wget ca-certificates python3 \
       build-essential autoconf automake libtool pkg-config m4 flex bison \
       cmake unzip make gcc g++ gawk libltdl-dev zlib1g-dev libbz2-dev \
       regina-rexx libregina3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/wrljet/hercules-helper.git /opt/hercules-helper \
    && git -C /opt/hercules-helper checkout --quiet ${HELPER_REF}

RUN sed -i "s|^git_repo_hercules=.*|git_repo_hercules=${HERCULES_REPO}|" \
      /opt/hercules-helper/sdl-hyperion.conf /opt/hercules-helper/hercules-helper.conf \
    && grep -qx "git_repo_hercules=${HERCULES_REPO}" /opt/hercules-helper/sdl-hyperion.conf

WORKDIR /build

RUN opt_configure_optimization="-O3" \
    /opt/hercules-helper/hercules-buildall.sh \
      --auto --flavor=sdl-hyperion --git-commit=${HERCULES_REF} \
      --accept-root --no-packages --no-tests --no-setcap \
      --no-envscript --no-bashrc \
      --prefix=/opt/hercules

FROM debian:trixie-slim

ARG HERCULES_REF
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 ca-certificates patch libltdl7 zlib1g libbz2-1.0 libregina3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=hercules /opt/hercules /opt/hercules
ENV PATH=/opt/hercules/bin:$PATH \
    LD_LIBRARY_PATH=/opt/hercules/lib:/opt/hercules/lib/hercules

# The build fails unless the banner names HERCULES_REF and every binary
# and module resolves all its libraries.
RUN banner=$(hercules --version 2>&1 | grep -m 1 HHC01413I) \
    && echo "$banner" \
    && sha=$(echo "$banner" | sed -n 's/.*-g\([0-9a-f]\{7,\}\).*/\1/p') \
    && case "${HERCULES_REF}" in \
         "$sha"*) [ -n "$sha" ] ;; \
         *) echo "Hercules is g$sha, expected ${HERCULES_REF}" >&2; false ;; \
       esac \
    && ! ldd /opt/hercules/bin/hercules /opt/hercules/lib/hercules/*.so | grep 'not found' \
    && command -v dasdinit dasdls

LABEL org.opencontainers.image.source="https://github.com/mvslovers/mvsce" \
      org.opencontainers.image.description="MVS/CE build environment: Hercules ${HERCULES_REF}, Python 3"
