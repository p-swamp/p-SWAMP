// Who this browser is, as far as the server is concerned.
//
// One id per browser profile, persisted in localStorage and resolved once at
// module load. Two properties follow from that, and the app depends on both:
//
//   1. **Every socket in the page shares it.** The server keeps one PMU pipeline
//      per client id, and the grid monitor opens five sockets at once — so an id
//      rolled per hook (which is what this replaced) would ask for five separate
//      pipelines per browser, each with its own replay and its own four threads.
//   2. **It survives a reload.** A remount, a navigation, a hard refresh and a
//      crashed tab all come back to the same id, and therefore rejoin the same
//      stream rather than starting a new one at 0 s.
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

const STORAGE_KEY = 'pswamp.client-id'

/** Positive, and inside the signed-32-bit range every consumer of this parses. */
function randomSeed(): string {
  return String(Math.floor(Math.random() * 2_147_483_647) + 1)
}

function resolveClientId(): string {
  // localStorage throws rather than returning null when storage is disabled
  // (Safari private browsing, embedded webviews, some enterprise policies), and
  // it throws on *read* as well as write. A client that cannot persist should
  // still work — it just gets a new pipeline on every reload, which is exactly
  // the behaviour this file replaced.
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored && /^\d{1,20}$/.test(stored)) return stored

    const fresh = randomSeed()
    window.localStorage.setItem(STORAGE_KEY, fresh)
    return fresh
  } catch {
    return randomSeed()
  }
}

/** This browser's client id. Resolved once; every socket sends the same value. */
export const CLIENT_ID = resolveClientId()
