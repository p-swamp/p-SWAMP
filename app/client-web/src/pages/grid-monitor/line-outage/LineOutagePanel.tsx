import { PlugZapIcon, WifiOffIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

import { Panel } from '../Panel'
import { type PanelVariant, tableDensity } from '../variant'
import { useLineOutageData } from './lineOutageContext'

function clockTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString(undefined, {
    hour12: false,
  })
}

/**
 * Branch connect/disconnect events, from p-SWAMP's `LineOutageDetectionApp`.
 *
 * A log rather than a state view: the detector publishes nothing at all while
 * the grid is intact, so an empty table is the healthy case and says so.
 *
 * Colours follow the alarm table's convention — a disconnect is loud, a
 * reconnect is not — rather than inventing a second palette for the same idea.
 */
export function LineOutagePanel({
  variant = 'dashboard',
}: {
  variant?: PanelVariant
}) {
  const { state, status, connected } = useLineOutageData()
  const events = state?.events ?? []
  const ready = connected && state !== null
  const outages = events.filter((e) => e.kind === 'disconnect').length
  const compact = variant === 'dashboard'

  return (
    <Panel
      title="Line outages"
      subtitle="Branches whose current magnitude dropped to zero, and their recovery"
      status={status}
      ready={ready}
      focusedClassName="w-full max-w-4xl"
      focusHref="/line-outage"
      variant={variant}
      minBodyClass="min-h-[152px]"
      contentClassName="p-0"
      badge={
        connected ? (
          <Badge variant={outages > 0 ? 'destructive' : 'secondary'}>
            <PlugZapIcon className="size-3" />
            {events.length === 0 ? 'No events' : `${events.length} events`}
          </Badge>
        ) : (
          <Badge variant="outline" className="text-muted-foreground">
            <WifiOffIcon className="size-3" />
            Offline
          </Badge>
        )
      }
      footer={
        state?.window_length
          ? `${state.app_name ?? 'LineOutageDetectionApp'} · ` +
            `${state.window_length.toFixed(2)}s window`
          : undefined
      }
    >
      <Table className={tableDensity(variant)}>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Event</TableHead>
            <TableHead>Branches</TableHead>
            {!compact && <TableHead className="text-right">Stations</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {events.map((event, i) => (
            <TableRow key={`${event.t}-${event.kind}-${i}`}>
              <TableCell className="tabular-nums">
                {clockTime(event.t)}
              </TableCell>
              <TableCell>
                <Badge
                  className={
                    event.kind === 'disconnect'
                      ? 'border-transparent bg-red-600/20 text-red-700 dark:text-red-400'
                      : 'border-transparent bg-emerald-600/15 text-emerald-700 dark:text-emerald-400'
                  }
                >
                  {event.kind === 'disconnect' ? 'Disconnected' : 'Reconnected'}
                </Badge>
              </TableCell>
              <TableCell className="font-mono text-xs whitespace-normal">
                {event.branches.join(', ')}
              </TableCell>
              {!compact && (
                <TableCell className="text-right text-muted-foreground tabular-nums">
                  {new Set(event.stations).size}
                </TableCell>
              )}
            </TableRow>
          ))}
          {events.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={compact ? 3 : 4}
                className="h-12 text-center text-muted-foreground"
              >
                All branches carrying current.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </Panel>
  )
}
