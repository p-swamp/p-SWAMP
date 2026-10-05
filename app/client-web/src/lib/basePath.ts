// The URL prefix this client is served under, discovered at *runtime*.
//
// Locally (dev, docker, minikube) the app lives at the origin root, `/`. In
// remote deployment it can sit behind a reverse proxy under
// `/p-swamp/`, which strips that prefix before forwarding — so
// the server still sees plain `/api/...` and needs no knowledge of it, but the
// *browser* must ask for every url with the prefix on the front.
//
// Rather than bake the prefix in at build time (which would make the image
// path-specific, and CI publishes exactly one), we derive it from where the
// bundle itself was loaded from. `vite.config.ts` sets `base: './'`, so
// index.html references its assets relatively and the browser resolves them
// against whatever path the page was served at. That means this module's own url
// already carries the answer:
//
//   https://host/p-swamp/assets/index-a1b2c3.js  →  '/p-swamp'
//   http://localhost:30080/assets/index-a1b2c3.js                 →  ''
//
// Under `npm run dev` there is no build and no assets/ dir — the url is
// `/src/lib/basePath.ts` — so the marker is absent and we fall through to '',
// which is correct: Vite serves the app at the root.
//
// Two invariants this rests on, both cheap to keep:
//
//   1. Built chunks live under `assets/` (Vite's default `assetsDir`, and the
//      same prefix `SPAStaticFiles` in server.py special-cases). Changing it
//      means changing the marker below.
//   2. **Routes stay one segment deep.** Relative asset urls resolve against the
//      directory of the current document, so `/prefix/phasors` resolves
//      `./assets/x.js` to `/prefix/assets/x.js` — right. A nested route like
//      `/prefix/phasors/detail` would resolve it to `/prefix/phasors/assets/…`
//      — wrong. If nested routes are ever needed, this approach has to be
//      replaced by a build-time `--base` or a server-injected `<base href>`.
//      A trailing slash is the same failure (`/prefix/phasors/` is a directory
//      deeper), so `SPAStaticFiles` redirects it to the bare route.

const ASSETS_MARKER = '/assets/'

function deriveBasePath(): string {
  const { pathname } = new URL(import.meta.url)
  const markerAt = pathname.lastIndexOf(ASSETS_MARKER)
  return markerAt === -1 ? '' : pathname.slice(0, markerAt)
}

/** The path prefix the app is mounted under: `''` at the origin root, otherwise
 *  a leading-slash path with no trailing slash (`'/p-swamp'`).
 *  Prepend it to any absolute path the browser is asked to fetch or navigate to;
 *  react-router does that for routes on its own, given `basename` (see App.tsx). */
export const BASE_PATH = deriveBasePath()
