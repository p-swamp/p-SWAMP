// Who this browser is, as far as the server is concerned.
//
// One id per browser profile, persisted in localStorage and resolved once at
// module load. Two properties follow from that, and the app depends on both:
//
//   1. **Every socket in the page shares it.** The server keeps a run per client
//      id for a recording (the PMU test streamer's), and a page may open several
//      sockets to it — so an id rolled per hook (which is what this replaced)
//      would ask for a separate replay per socket. (The grid monitor's live grid
//      is one for every client; its sockets still say whose they are.)
//   2. **It survives a reload.** A remount, a navigation, a hard refresh and a
//      crashed tab all come back to the same id, and therefore rejoin the same
//      replay rather than starting a new one at 0 s.
//
// Note the scope is the *origin*, not the tab: two tabs on the same profile are
// one client and watch the same replay. That is the intended reading of "come
// back to their own stream" — a person, not a window.
//
// Deliberately a plain random integer rather than a UUID: every server endpoint
// checks it against one pattern (CLIENT_ID_PATTERN, digits) and closes the
// socket with 1008 on anything else. It is not a secret and not
// authentication — the server says as much — so randomness only has to avoid
// collisions between colleagues, not resist guessing.
//
// **`?client_id=<digits>` on any page url overrides it for that tab**, so one
// browser can be several clients: a load test in tabs, two clients side by
// side. Private windows share one localStorage, so they cannot do that. The
// override is kept in sessionStorage, which is per tab: a navigation (which
// drops the query) and a reload keep it, and the profile's id in localStorage
// is left alone.

const STORAGE_KEY = 'pswamp.client-id'
const TAB_STORAGE_KEY = 'pswamp.client-id.tab'
const ID = /^\d{1,20}$/

/** Positive, and inside the signed-32-bit range every consumer of this parses. */
function randomSeed(): string {
  return String(Math.floor(Math.random() * 2_147_483_647) + 1)
}

/** The tab's override: `?client_id=` in the url, else one kept from earlier in this tab. */
function tabClientId(): string | null {
  const requested = new URLSearchParams(window.location.search).get('client_id')
  if (requested !== null && !ID.test(requested)) {
    console.warn(`ignoring ?client_id=${requested}: it must be 1 to 20 digits`)
  }
  const fromUrl = requested !== null && ID.test(requested) ? requested : null
  try {
    if (fromUrl) {
      window.sessionStorage.setItem(TAB_STORAGE_KEY, fromUrl)
      return fromUrl
    }
    const kept = window.sessionStorage.getItem(TAB_STORAGE_KEY)
    return kept && ID.test(kept) ? kept : null
  } catch {
    return fromUrl // storage disabled: the url's id still applies to this page load
  }
}

function resolveClientId(): string {
  // localStorage throws rather than returning null when storage is disabled
  // (Safari private browsing, embedded webviews, some enterprise policies), and
  // it throws on *read* as well as write. A client that cannot persist should
  // still work — it just gets a new pipeline on every reload, which is exactly
  // the behaviour this file replaced.
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored && ID.test(stored)) return stored

    const fresh = randomSeed()
    window.localStorage.setItem(STORAGE_KEY, fresh)
    return fresh
  } catch {
    return randomSeed()
  }
}

/** This tab's client id: the url's override, else the browser's. Resolved once; every socket sends the same value. */
export const CLIENT_ID = tabClientId() ?? resolveClientId()
