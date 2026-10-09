import { ExternalLinkIcon } from 'lucide-react'
import { NavLink, Outlet } from 'react-router'

import { ErrorTray } from '@/components/ErrorTray'
import { CLIENT_ID } from '@/lib/clientId'
import { BASE_PATH } from '@/lib/basePath'
import { cn } from '@/lib/utils'

/**
 * The shell every page renders inside: a nav bar listing the apps, the outlet
 * the page itself fills, and a footer naming this browser. Registered as the
 * layout route in App.tsx, so adding a page means adding a NAV_ITEMS entry plus
 * a <Route>.
 *
 * Nothing here selects a backend: every socket resolves against the origin the
 * client was served from (see src/lib/servers.ts), so the several panels of the
 * grid monitor are necessarily views of one and the same server.
 */
const NAV_ITEMS = [
  // `end` on the index entry: NavLink matches descendant paths by default, and
  // "/" is a prefix of every route — without it the monitor would render as the
  // active link on every page.
  { to: '/', label: 'Monitor', end: true },
  { to: '/pmu-test-streamer', label: 'PMU Test Streamer', end: false },
  { to: '/reference-subapp', label: 'Reference example', end: false },
  { to: '/rolling-frequency', label: 'Rolling frequency', end: false },
]

function isLocalhost(): boolean {
  const { hostname } = window.location
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]'
}

// The git commit this frontend bundle was built from, inlined by Vite from the
// Dockerfile's GIT_SHA build arg (CI passes github.sha). Empty in dev and in an
// unstamped build — which is why the footer shows this line only off localhost,
// where the value comes from a CI-built image and answers "which commit is this
// deploy?".
const GIT_SHA = import.meta.env.VITE_GIT_SHA ?? ''

export function AppLayout() {
  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="flex items-center gap-6 border-b px-6 py-3">
        <span className="font-semibold tracking-tight">P-SWAMP</span>
        <nav className="flex items-center gap-4 text-sm">
          {NAV_ITEMS.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'transition-colors hover:text-foreground',
                  isActive
                    ? 'font-medium text-foreground'
                    : 'text-muted-foreground',
                )
              }
            >
              {label}
            </NavLink>
          ))}
          {isLocalhost() && (
            <a
              href={`${BASE_PATH}/docs`}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 text-muted-foreground transition-colors hover:text-foreground"
            >
              API doc
              <ExternalLinkIcon className="size-3.5" aria-hidden="true" />
            </a>
          )}
        </nav>
      </header>

      {/* Outside the outlet, so it survives navigation. */}
      <ErrorTray />

      <main className="flex flex-1 items-center justify-center p-6">
        <Outlet />
      </main>

      {/* The client id is worth surfacing now that it decides which server-side
          PMU stream you are watching: two browsers showing different instants of
          the recording is correct behaviour, and this is what explains it. Also
          the thing to quote when a server log line names a client.

          Also show what git SHA/version we are running off of, so its easy to see what has been
          deployed to remote env at any time*/}
      <footer className="px-6 py-2 text-right text-xs text-muted-foreground/60">
        client id: <span className="font-mono">{CLIENT_ID}</span>
        {!isLocalhost() && (
          <>
            <br />
            built off git SHA:{' '}
            <span className="font-mono">{GIT_SHA || 'unknown'}</span>
          </>
        )}
      </footer>
    </div>
  )
}
