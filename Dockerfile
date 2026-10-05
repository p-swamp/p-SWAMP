# State server image, with the web client baked in: the first stage below builds
# app/client-web to static assets that the server stage serves at / alongside /ws
# (same process, port, and origin) — so one image and one Service serve both.
#
# --- web client build stage -------------------------------------------------
#
# Build the Vite/React/TS web client to plain static files. A pinned Node image
# runs `npm ci` + `vite build`, emitting /web/dist (index.html + favicon/icons +
# hashed files under assets/). Only that dist/ is copied into the final image —
# Node and node_modules never ship. Pinned to a digest for reproducible builds
# (the tag is kept as documentation); this is the multi-arch index digest, so
# arm64/amd64 both resolve. Resolved 2026-09-01 from tag 24-bookworm-slim.
# TEMP: needed by the per-arch OpenBLAS workaround stages further down; see
# the TEMP note there for what it is and when to remove it.
ARG TARGETARCH

FROM node:24-bookworm-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e AS web-build
WORKDIR /web
# Copy only the manifests first so `npm ci` is cached and re-runs only when the
# lockfile changes, not on every source edit.
COPY app/client-web/package.json app/client-web/package-lock.json ./
RUN npm ci
# The git commit this image is built from, threaded in as a build arg and exposed
# to Vite as VITE_GIT_SHA so `vite build` inlines it into the bundle
# (import.meta.env.VITE_GIT_SHA). The footer shows it on deployed origins so a
# visitor can tell exactly which commit the frontend was built off. Declared
# *after* `npm ci` so a changing SHA doesn't bust that cached layer; the source
# COPY + build below re-run every commit anyway. Empty in a plain `docker build`
# with no --build-arg (compose/minikube dev) — fine, the footer only shows it off
# localhost. CI's build-container.yml passes github.sha, and a downstream
# deployment building its own image should pass `git rev-parse HEAD`.
ARG GIT_SHA=""
ENV VITE_GIT_SHA=$GIT_SHA
COPY app/client-web/ ./
RUN npm run build

# --- server stage -----------------------------------------------------------
#
# Base: Astral's official uv image (Python 3.14.8 on Debian 13 "trixie" slim).
# Pinned to a digest for reproducible builds — the readable tag is kept as
# documentation, but Docker enforces the @sha256. This is the multi-arch OCI
# index digest, so arm64/amd64 still resolve automatically.
# The tag names only the minor version, so the digest is what fixes the patch:
# after a refresh, check `python --version` in the image and keep
# app/server-python/.python-version in step with it.
# trixie, not bookworm: the python3.14-bookworm-slim tag is no longer updated
# (Python 3.14.2 and uv 0.9.30 when checked on 2026-10-05).
# Resolved 2026-10-05 from tag python3.14-trixie-slim. To refresh:
#   curl -s "https://ghcr.io/token?scope=repository:astral-sh/uv:pull" | ...
#   curl -sI -H "Authorization: Bearer <token>" \
#     -H "Accept: application/vnd.oci.image.index.v1+json" \
#     https://ghcr.io/v2/astral-sh/uv/manifests/python3.14-trixie-slim
FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim@sha256:8e88a074b0969bdc461f681727238e109438d70771828909f9ef19cfcc96c43a AS runtime-base

# TEMP: OpenBLAS SIGILL workaround for arm64 images. Remove once a numpy release
# bundles an OpenBLAS newer than v0.3.34 (see below for how to check).
#
# The problem: numpy's wheels bundle OpenBLAS, which picks a CPU-specific kernel
# at import. Up to and including v0.3.34 it selects its ARMV9SME kernel whenever
# the CPU reports SME, without checking for SVE. Apple silicon (M4) reports SME
# but has no plain SVE, so on an arm64 Linux VM or container on such a Mac the
# kernel's setup runs an SVE instruction the CPU lacks and `import numpy` dies
# with SIGILL (exit 132, no traceback). Here that kills the `import server`
# check below, and the server at start. Fixed upstream in OpenBLAS df46d62
# ("Confirm SVE capability before assigning ARMV9SME", issue #6011, merged
# 2026-09-05), which is in no release yet. numpy 2.5.2, 2.5.3 and the nightly
# wheel all still crash, checked 2026-10-05.
#
# The workaround: OPENBLAS_CORETYPE=ARMV8 skips the detection and uses the
# generic Armv8 kernels. Safe on every arm64 CPU, a little slower for linear
# algebra, which this server barely does. Set on arm64 only, so amd64 images
# (what CI builds) are unchanged. Needs BuildKit, which sets TARGETARCH; it is
# the default builder for docker, compose and minikube.
#
# To revert: once a numpy release bundles a fixed OpenBLAS, bump numpy in both
# lockfiles, then check on an Apple-silicon arm64 VM that this exits 0:
#   env -u OPENBLAS_CORETYPE uv run --no-project --with numpy==<new> \
#     python -c "import numpy; numpy.linalg.inv(numpy.eye(50))"
# Then delete the two per-arch stages below, drop the `AS runtime-base` and the
# `FROM runtime-${TARGETARCH}`, and delete the `ARG TARGETARCH` above.
FROM runtime-base AS runtime-amd64

FROM runtime-base AS runtime-arm64
ENV OPENBLAS_CORETYPE=ARMV8

FROM runtime-${TARGETARCH}

# The image mirrors the *whole repo* at its real depth, not just the server dir
# flattened to /app. The depth is required for the build to work at all, not a
# matter of taste.
#
# app/server-python/pyproject.toml declares p-swamp -- the desktop package at the
# repo root -- as an editable path dependency, "../../", resolved relative to the
# manifest's own directory. uv refuses to normalise a relative path above its
# base directory: it does not clamp at the filesystem root the way a shell does.
# So with the server at /app, "../../" would be unresolvable and the manifest
# would need a second, image-only variant. Keeping the repo's own depth means one
# literal path string is correct both on a development machine and here.
ARG REPO_DIR=/workspace/p-SWAMP
ARG SERVER_DIR=${REPO_DIR}/app/server-python

WORKDIR ${SERVER_DIR}

# curl is used by the compose healthcheck to probe /healthz.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependency manifest first, on its own layer: the install below is then cached
# and re-runs only when pyproject.toml/uv.lock actually change, not on every
# source edit. Same trick as `npm ci` in the web-build stage above.
COPY app/server-python/pyproject.toml app/server-python/uv.lock ./

# The root manifest, and only the manifest, before the dependency install.
# p-swamp is an editable path dependency, and uv insists on generating its
# package metadata while resolving -- even with --no-emit-package below, which
# only suppresses it from the *output*. So the root project has to exist here,
# but nothing of it is needed yet except what declares its metadata (README.md
# comes along because the root manifest's `readme =` points at it, and uv reads
# it to build the metadata). Copying those two files rather than the whole tree
# is what keeps the expensive wheel install below on a layer that a change to
# root src/pswamp/ does not invalidate.
COPY pyproject.toml README.md ${REPO_DIR}/

# The shared core (core/), the second editable path dependency: its manifest
# now, for resolving; its source further down.
COPY core/pyproject.toml core/README.md ${REPO_DIR}/core/

# The modules (modules/), the third: same again.
COPY modules/pyproject.toml modules/README.md ${REPO_DIR}/modules/

# pyproject.toml declares the direct dependencies; uv.lock pins the whole
# transitive closure resolved from it. Install system-wide at build time, so
# container startup needs no network and no runtime resolution.
#
# --locked asserts the lockfile exists and still matches pyproject.toml: change a
# dependency without re-running `uv lock`, or forget to COPY the lock, and the
# build fails loudly here instead of silently re-resolving to whatever the index
# serves today. --no-emit-project skips this non-packaged project itself, and
# --no-dev keeps the linter out of the image. Hashes are kept (no --no-hashes),
# so uv verifies every artifact it installs; the lock carries wheel hashes for
# both amd64 and arm64, so this stays multi-arch.
#
# --no-emit-package p-swamp excludes the root project itself, which is a path
# dependency rather than something to fetch from an index; it is installed from
# its own layer below. Its third-party requirements (numpy, scipy, pandas) are
# still emitted here, so they stay in this cached, hash-verified layer.
#
# synchrophasor is excluded deliberately. It is p-SWAMP's C37.118 implementation,
# declared as one of its dependencies but imported only by the live-PMU and
# playback paths -- neither of which this server uses, since it replays an
# already-decoded recording. It is also the one dependency fetched from git
# rather than an index, so keeping it out means this image needs no git, no
# network access to GitHub, and no hashless VCS pin sitting among otherwise
# fully hash-verified packages. The import check after the source copy below is
# what keeps that a checked decision rather than a hopeful one.
RUN uv export --locked --no-emit-project --no-dev \
      --no-emit-package p-swamp --no-emit-package pswamp-core \
      --no-emit-package pswamp-modules \
      --no-emit-package synchrophasor \
      -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# The desktop package's source: root src/pswamp/, which supplies the PMU
# decoding, time-window storage and monitoring applications this server is a
# front end for. It lands at ${REPO_DIR}/src, exactly where the manifest's
# "../../" resolves to from the server directory -- see the workspace note at the
# top of this stage.
#
# Only src/ is copied, not the whole repo: examples/, tests/ and build/ are
# excluded in .dockerignore, so they never reach the daemon in the first place.
#
# Copied after the dependency install so editing src/pswamp/ does not invalidate
# the layer holding every third-party wheel; only the few seconds of --no-deps
# below re-run. --no-deps is safe precisely because those dependencies were
# installed above, and asserts it: were the root manifest to gain a dependency
# without app/server-python/uv.lock being refreshed, this would fail at import
# rather than silently resolving.
#
# Editable, so the copied source is the live import path and `docker compose
# watch` can sync edits to root src/pswamp/ into a running container for uvicorn
# --reload to pick up — the same loop the server's own src/ already has. Nothing
# is published from here, so an editable install in the image costs nothing.
COPY src/ ${REPO_DIR}/src/
RUN uv pip install --system --no-deps -e ${REPO_DIR}

# The shared core, installed editable like the desktop package so compose watch
# can sync edits in. core/tests/ is kept out by .dockerignore.
COPY core/ ${REPO_DIR}/core/
RUN uv pip install --system --no-deps -e ${REPO_DIR}/core

# The modules, their pipelines and the example sources, installed the same
# way. They depend on the core only, so a worker imports them from any working
# directory. Each module's tests/ folder is kept out by .dockerignore.
COPY modules/ ${REPO_DIR}/modules/
RUN uv pip install --system --no-deps -e ${REPO_DIR}/modules

# Server source last, so editing it doesn't invalidate the dependency layer
# above. The image mirrors the repo, so server.py and the app packages beside it
# land in <server dir>/src exactly as they sit in the working tree.
# Copying the directory rather than naming files means a new module — or a whole
# new app package — needs no Dockerfile edit.
COPY app/server-python/src/ ./src/

# Prove the dependency set is actually sufficient. Importing server.py pulls in
# every app package, and through them the whole p-SWAMP import graph this server
# touches -- so a missing dependency fails the build here rather than at runtime,
# in a container someone has already deployed. In particular it is what makes
# excluding synchrophasor above a checked decision. Importing is side-effect
# free: the server only binds a port under __main__.
RUN cd src && python -c "import server" && echo "import graph OK"

# Web client assets: the Vite build output from the web-build stage above,
# dropped where server.py mounts it — static/ beside the source, i.e.
# Path(__file__).parent / "static". Content-hashed filenames, so it's safe to
# cache hard.
COPY --from=web-build /web/dist ./src/static

# Run as a non-root user (k8s-friendly).
RUN useradd --create-home --uid 10001 app
USER app

# Run from the source dir, so `server.py`, `server:app` (the form compose's
# uvicorn --reload override uses) and the app packages it imports (`import
# pmu_test_streamer`) resolve off the working directory with no PYTHONPATH or
# --app-dir plumbing. Deps were installed system-wide above, so nothing here depends on
# where in the filesystem this sits.
WORKDIR ${SERVER_DIR}/src

# 0.0.0.0 so the port is reachable outside the container; see server.py.
ENV HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

# Plain python: deps are already installed, so the PEP 723 metadata is ignored
# and there's no uv resolution at start.
CMD ["python", "server.py"]
