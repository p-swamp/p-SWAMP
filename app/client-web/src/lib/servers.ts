// Where the web client's requests point: always the origin the page was served
// from. There is no backend picker and no address table.
//
// Two kinds of address live here, because the two directions use two transports.
// State comes *down* over a WebSocket (the `*_WS_PATH` consts); commands go *up*
// as POSTs (the `*_API_PATH` consts, which are the app's prefix — each endpoint
// appends its own path). Both resolve against the same origin by the same rule.
//
// That one rule covers both ways this app runs, because dev is made to look like
// production rather than special-cased:
//
//   - shipped build — the client is *served by* the backend (container, minikube
//     NodePort, any remote cluster), so its own origin already is the backend.
//   - `npm run dev` — the page's origin is the Vite dev server, whose proxy
//     forwards the whole /api prefix (WebSocket upgrades included) to the local
//     docker server on :8000. See `server.proxy` in vite.config.ts.
//
// So aiming dev at a different backend is a proxy-target edit in vite.config.ts,
// not a runtime choice in the UI.

import { BASE_PATH } from '@/lib/basePath'

// Each app's WebSocket endpoint. Every backend app package is mounted under its
// own /api/<app> prefix (see APPS in app/server-python/src/server.py), so these
// paths are the client-side half of that contract — one const per app, rather
// than a literal repeated across the hooks that connect.
export const PMU_STREAM_WS_PATH = '/api/pmu-test-streamer/ws'
export const APP_STATUS_WS_PATH = '/api/app-status/ws'
export const TIME_WINDOW_WS_PATH = '/api/time-window/ws'
export const ISLANDING_WS_PATH = '/api/islanding/ws'
export const PHASORS_WS_PATH = '/api/phasors/ws'
export const LINE_OUTAGE_WS_PATH = '/api/line-outage/ws'
export const REFERENCE_SUBAPP_WS_PATH = '/api/reference-subapp/ws'
// Not a page's: the layout opens this one, for the error tray.
export const ERRORS_WS_PATH = '/api/errors/ws'

// Each app's REST prefix — where its commands are POSTed. Same value as the app's
// mount prefix in APPS (app/server-python/src/server.py); an endpoint path is
// appended by the caller, e.g. `${PMU_STREAM_API_PATH}/playback/play`.
export const PMU_STREAM_API_PATH = '/api/pmu-test-streamer'
export const TIME_WINDOW_API_PATH = '/api/time-window'
export const ISLANDING_API_PATH = '/api/islanding'
export const REFERENCE_SUBAPP_API_PATH = '/api/reference-subapp'

// The grid topology is static, so it is fetched over HTTP rather than pushed.
export const GRID_MODEL_PATH = '/api/grid/model'

/** The full http(s):// URL for a path on the serving origin.
 *
 *  The plain-HTTP twin of resolveServerUrl below, and the same rule: the page's
 *  own origin, plus BASE_PATH for the remote reverse proxy's mount prefix. Used
 *  for command POSTs (see lib/commands.ts) and for the static GETs. */
export function resolveApiUrl(path: string): string {
  return `${window.location.origin}${BASE_PATH}${path}`
}

/** The full ws:// (or wss://) URL for one app's endpoint on the serving origin,
 *  derived from the current page so it follows http→ws / https→wss automatically.
 *
 *  BASE_PATH is empty locally and `/p-swamp` behind the remote
 *  reverse proxy, which strips it again before the request reaches the server —
 *  so the paths above stay written the way the server actually mounts them.
 *
 *  `wsPath` is one of the *_WS_PATH consts above. */
export function resolveServerUrl(wsPath: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${BASE_PATH}${wsPath}`
}
