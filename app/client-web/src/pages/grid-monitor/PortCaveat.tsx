import { AlertTriangleIcon } from 'lucide-react'

/**
 * Status banner at the top of the grid monitor.
 *
 * This page is a rough port of the Qt front end and is not yet something to
 * trust or build on, so it says so where it will actually be read — on the page
 * itself, rather than only in the repo docs. The split matters: the *analysis*
 * below is the long-standing Python in `src/pswamp/`, reached unchanged; only
 * this presentation layer is new and unreviewed.
 *
 * One line, with the rest behind it: the monitor is a window with the
 * viewport's height, and a banner three lines tall came out of the grid view.
 * The warning itself stays in view; the background unfolds on a click.
 *
 * Remove it when the client has been reviewed and solidified — see
 * doc/WIP-context-port-from-qt-to-web-frontend.md §10.
 *
 * Deliberately not red: nothing is broken, and red would compete with the alarm
 * dock, where red has to mean a grid event.
 */
export function PortCaveat() {
  return (
    <details className="group shrink-0 rounded-md border border-amber-300 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-100">
      <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
        <AlertTriangleIcon className="size-3.5 shrink-0" />
        <span className="shrink-0 font-semibold">
          Preliminary rough port of the Qt frontend code
        </span>
        <span className="min-w-0 truncate group-open:hidden">
          — largely LLM-generated, probably incomplete, may very well have
          serious flaws, and needs to be reviewed before it is iterated on
          further.
        </span>
        <span className="ml-auto shrink-0 underline underline-offset-2 group-open:hidden">
          more
        </span>
        <span className="ml-auto hidden shrink-0 underline underline-offset-2 group-open:inline">
          less
        </span>
      </summary>
      <p className="mt-1.5 max-w-5xl">
        An exploratory early port of some of the prexisting QT GUI to TS+React,
        connecting existing pSWAMP models and algorithms. Only the Qt GUI is
        ported here: the python server process reuses Hallvars existing Python
        models and algorithms, which still live in <code>/src/pswamp/</code>{' '}
        (for now).{' '}
        <b>
          Note that this web frontend draft currently is largely LLM-generated,
          probably incomplete, may very well have serious flaws, and it needs to
          be reviewed before it is iterated on further.
        </b>
      </p>
    </details>
  )
}
