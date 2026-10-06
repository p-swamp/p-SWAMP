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
# Base: Astral's official uv image (Python 3.11 on Debian 12 "bookworm" slim).
# Pinned to a digest for reproducible builds — the readable tag is kept as
# documentation, but Docker enforces the @sha256. This is the multi-arch OCI
# index digest, so arm64/amd64 still resolve automatically.
# Resolved 2026-06-06 from tag python3.11-bookworm-slim. To refresh:
#   curl -s "https://ghcr.io/token?scope=repository:astral-sh/uv:pull" | ...
#   curl -sI -H "Authorization: Bearer <token>" \
#     -H "Accept: application/vnd.oci.image.index.v1+json" \
#     https://ghcr.io/v2/astral-sh/uv/manifests/python3.11-bookworm-slim
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim@sha256:4f5d923c9dcea037f57bda425dd209f3ec643da2f0b74227f68d09dab0b3bb36

# The image mirrors the *whole repo* at its real depth, not just the server dir
# flattened to /app. The depth is required for the build to work at all, not a
# matter of taste.
#
# The repo root is a uv workspace (root pyproject.toml + the one uv.lock), with
# core/, modules/ and app/server-python/ as members, so the root manifest and
# lock land at ${REPO_DIR} and each member at its own path below it.
# app/server-python/pyproject.toml also declares p-swamp -- the desktop package
# in desktop/, outside the workspace -- as an editable path dependency,
# "../../desktop", resolved relative to the manifest's own directory. uv refuses
# to normalise a relative path above its base directory: it does not clamp at
# the filesystem root the way a shell does. So with the server at /app,
# "../../desktop" would be unresolvable and the manifest would need a second,
# image-only variant. Keeping the repo's own depth means one literal path string
# is correct both on a development machine and here.
ARG REPO_DIR=/workspace/p-SWAMP
ARG SERVER_DIR=${REPO_DIR}/app/server-python

WORKDIR ${REPO_DIR}

# curl is used by the compose healthcheck to probe /healthz.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependency manifests first, on their own layers: the install below is then
# cached and re-runs only when a pyproject.toml/uv.lock actually changes, not on
# every source edit. Same trick as `npm ci` in the web-build stage above. The
# workspace root's manifest and its one lockfile first, then the server member's
# manifest.
COPY pyproject.toml uv.lock ./
COPY app/server-python/pyproject.toml ${SERVER_DIR}/

# The desktop package's manifest, and only the manifest, before the dependency
# install. p-swamp is an editable path dependency, and uv insists on generating
# its package metadata while resolving -- even with --no-emit-package below,
# which only suppresses it from the *output*. So the desktop project has to
# exist here, but nothing of it is needed yet except what declares its metadata
# (README.md comes along because its manifest's `readme =` points at it, and uv
# reads it to build the metadata). Copying those two files rather than the
# whole tree is what keeps the expensive wheel install below on a layer that a
# change to desktop/src/pswamp/ does not invalidate.
COPY desktop/pyproject.toml desktop/README.md ${REPO_DIR}/desktop/

# The shared core (core/), a workspace member: its manifest now, for resolving;
# its source further down.
COPY core/pyproject.toml core/README.md ${REPO_DIR}/core/

# The modules (modules/), the third: same again.
COPY modules/pyproject.toml modules/README.md ${REPO_DIR}/modules/

# The manifests declare the direct dependencies; the workspace uv.lock pins the
# whole transitive closure resolved from them. --package pswamp-server exports
# what the server needs (and so, through it, what the core and modules need). Install system-wide at build time, so
# container startup needs no network and no runtime resolution.
#
# --locked asserts the lockfile exists and still matches pyproject.toml: change a
# dependency without re-running `uv lock`, or forget to COPY the lock, and the
# build fails loudly here instead of silently re-resolving to whatever the index
# serves today. --no-emit-workspace skips the workspace members themselves (the
# non-packaged server, and the core and modules, installed from their own layers
# below), and --no-dev keeps the linter out of the image. Hashes are kept (no --no-hashes),
# so uv verifies every artifact it installs; the lock carries wheel hashes for
# both amd64 and arm64, so this stays multi-arch.
#
# --no-emit-package p-swamp excludes the desktop project itself, which is a path
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
RUN uv export --locked --package pswamp-server --no-emit-workspace --no-dev \
      --no-emit-package p-swamp \
      --no-emit-package synchrophasor \
      -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# The desktop package's source: desktop/src/pswamp/, which supplies the PMU
# decoding, time-window storage and monitoring applications this server is a
# front end for. It lands at ${REPO_DIR}/desktop/src, under exactly where the
# manifest's "../../desktop" resolves to from the server directory -- see the
# workspace note at the top of this stage.
#
# Only desktop/src/ is copied, not the whole desktop tree: desktop/examples/,
# desktop/tests/ and desktop/build/ are excluded in .dockerignore, so they never
# reach the daemon in the first place.
#
# Copied after the dependency install so editing desktop/src/pswamp/ does not invalidate
# the layer holding every third-party wheel; only the few seconds of --no-deps
# below re-run. --no-deps is safe precisely because those dependencies were
# installed above, and asserts it: were desktop/pyproject.toml to gain a
# dependency without the workspace uv.lock being refreshed, this would fail at
# import rather than silently resolving.
#
# Editable, so the copied source is the live import path and `docker compose
# watch` can sync edits to desktop/src/pswamp/ into a running container for uvicorn
# --reload to pick up — the same loop the server's own src/ already has. Nothing
# is published from here, so an editable install in the image costs nothing.
COPY desktop/src/ ${REPO_DIR}/desktop/src/
RUN uv pip install --system --no-deps -e ${REPO_DIR}/desktop

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
COPY app/server-python/src/ ${SERVER_DIR}/src/

# Prove the dependency set is actually sufficient. Importing server.py pulls in
# every app package, and through them the whole p-SWAMP import graph this server
# touches -- so a missing dependency fails the build here rather than at runtime,
# in a container someone has already deployed. In particular it is what makes
# excluding synchrophasor above a checked decision. Importing is side-effect
# free: the server only binds a port under __main__.
RUN cd ${SERVER_DIR}/src && python -c "import server" && echo "import graph OK"

# Web client assets: the Vite build output from the web-build stage above,
# dropped where server.py mounts it — static/ beside the source, i.e.
# Path(__file__).parent / "static". Content-hashed filenames, so it's safe to
# cache hard.
COPY --from=web-build /web/dist ${SERVER_DIR}/src/static

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
