import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Maximize2Icon } from 'lucide-react'

import { Alert, AlertTitle } from '@/components/ui/alert'
import {
  Card,
  CardAction,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import type { ConnStatus } from '@/hooks/useServerSocket'
import { cn } from '@/lib/utils'

import type { PanelVariant } from './variant'

const ALWAYS_ONLINE: ConnStatus = { kind: 'online' }

/**
 * The frame every monitor panel renders inside.
 *
 * Each panel has its own WebSocket, so each reports its own connection state —
 * one can be dark while its neighbours are live, and that should be visible
 * rather than smoothed over. This shell owns that: the waiting/offline banner
 * used to be copy-pasted, identically, in all four pages.
 *
 * **It also owns the dashboard/focused convention**, which is why it takes
 * `variant`. Every panel is rendered twice — as a dock in the main window on
 * `/`, and full-size on its own route — and the difference is the same handful
 * of decisions every time:
 *
 * - On the dashboard it is a **dock**, after the Qt main window's: a slim title
 *   bar over a tightly packed body, sized by the window around it rather than
 *   by its content. Focused, it is a card with room to breathe.
 * - The subtitle is worth its space only when focused.
 * - The expand link only makes sense on the dashboard (a focused panel must not
 *   offer to open the page you are already on).
 * - The width applies only when the panel owns the page.
 *
 * Each panel used to spell those out as `variant === …` ternaries of its own —
 * six copies of one convention, and six chances to get it subtly different. A
 * panel now states facts (here is my subtitle, my route, my width) and this
 * decides when they apply.
 */
export function Panel({
  title,
  subtitle,
  actions,
  badge,
  status = ALWAYS_ONLINE,
  ready = true,
  variant = 'dashboard',
  drawsWithoutData = false,
  focusHref,
  focusedClassName,
  minBodyClass = 'min-h-[240px]',
  fill = false,
  footer,
  className,
  contentClassName,
  children,
}: {
  title: string
  /** One line under the title, shown in the focused variant only: on the
   *  dashboard the panels around it are the context, and the space is not there
   *  to spare. */
  subtitle?: string
  /** Controls that belong to the panel as a whole — a view switch, say — shown
   *  in the title bar ahead of the badge. */
  actions?: ReactNode
  /** Live indicator shown at the top right, beside the expand link. */
  badge?: ReactNode
  /** This panel's own socket state. Left out by the rare panel that has no
   *  socket and so nothing to wait for. */
  status?: ConnStatus
  /** Connected *and* the first message has arrived. */
  ready?: boolean
  /** How this panel is being rendered: as a dock in the main window, or as its
   *  own page. Defaults to the dock. */
  variant?: PanelVariant
  /** Set when the body is worth showing before any message arrives — the grid
   *  view, whose topology is static and fetched separately from the sockets that
   *  colour it. Such a panel renders its body immediately, with the waiting
   *  notice above it rather than in place of it. Panels whose body is nothing
   *  but live data (a dial with no phasors, a table with no rows) leave this
   *  off, so they show the notice alone rather than an empty frame. */
  drawsWithoutData?: boolean
  /** This panel's own full-size route. The expand link is rendered in the
   *  dashboard variant only. */
  focusHref?: string
  /** Width (or any class) that applies only when this panel owns the page.
   *  Ignored on the dashboard, where the window decides. */
  focusedClassName?: string
  /** Height reserved for the waiting notice when focused, so the page does not
   *  jump when the first message lands. A dock is sized by the window instead. */
  minBodyClass?: string
  /** Dock only: take whatever height the window has left, and scroll inside it,
   *  rather than being as tall as the content. */
  fill?: boolean
  footer?: ReactNode
  className?: string
  contentClassName?: string
  children: ReactNode
}) {
  const focused = variant === 'focused'
  const notice = (
    <Alert
      variant={
        status.kind === 'offline' && status.isError ? 'destructive' : 'default'
      }
      className={cn(!focused && 'px-2.5 py-1.5 text-xs')}
    >
      <AlertTitle>
        {status.kind === 'online' ? 'Waiting for state…' : status.label}
      </AlertTitle>
    </Alert>
  )
  const expand = !focused && focusHref && (
    <Link
      to={focusHref}
      aria-label={`Open ${title} full size`}
      className="text-muted-foreground transition-colors hover:text-foreground"
    >
      <Maximize2Icon className="size-3.5" />
    </Link>
  )

  if (!focused) {
    return (
      // min-w-0: a flex or grid item defaults to min-width:auto, so a wide
      // canvas or table inside would otherwise force its whole column open.
      <section
        aria-label={title}
        className={cn(
          'flex min-w-0 shrink-0 flex-col overflow-hidden rounded-md border bg-card text-card-foreground',
          fill && 'min-h-0 flex-1',
          className,
        )}
      >
        <header className="flex h-8 shrink-0 items-center gap-2 border-b bg-muted/70 px-2.5">
          <h2 className="truncate text-xs font-semibold">{title}</h2>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            {actions}
            {badge}
            {expand}
          </div>
        </header>

        <div
          className={cn(
            // relative: the waiting notice of a panel that draws without data
            // is laid over its body rather than pushing it down.
            'relative min-h-0 p-2',
            fill && 'flex-1 overflow-auto',
            contentClassName,
          )}
        >
          {ready ? (
            children
          ) : drawsWithoutData ? (
            <>
              {children}
              <div className="pointer-events-none absolute inset-x-2 top-2">
                {notice}
              </div>
            </>
          ) : (
            <div className="flex min-h-16 items-center justify-center p-2">
              {notice}
            </div>
          )}
        </div>

        {footer && (
          <footer className="shrink-0 truncate border-t px-2.5 py-1 text-xs text-muted-foreground tabular-nums">
            {footer}
          </footer>
        )}
      </section>
    )
  }

  return (
    <Card className={cn('min-w-0 gap-0', focusedClassName, className)}>
      <CardHeader className="border-b">
        <CardTitle className="text-base">{title}</CardTitle>
        {subtitle && <span className="text-sm text-gray-500">{subtitle}</span>}
        <CardAction className="flex items-center gap-2 self-center">
          {actions}
          {badge}
        </CardAction>
      </CardHeader>

      <CardContent className={cn('pt-6', contentClassName)}>
        {ready ? (
          children
        ) : drawsWithoutData ? (
          <div className="space-y-3">
            {notice}
            {children}
          </div>
        ) : (
          <div className={cn('flex items-center justify-center', minBodyClass)}>
            {notice}
          </div>
        )}
      </CardContent>

      {footer && (
        <CardFooter className="border-t pt-4 text-sm text-muted-foreground tabular-nums">
          {footer}
        </CardFooter>
      )}
    </Card>
  )
}
