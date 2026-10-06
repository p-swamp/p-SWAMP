import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

import { type PanelVariant, tableDensity } from '../variant'
import type { AppStatusRow, AppStatusValue } from './useAppStatusSocket'

/**
 * Row colours, the Qt status table's own (`AppStatusMonitoringWidget.update`):
 * green healthy, yellow warning, red emergency, blue still starting up. The
 * whole row is tinted, as there, so a column of statuses reads from across the
 * room rather than badge by badge.
 */
const ROW_BACKGROUND: Record<AppStatusValue, string> = {
  OK: 'rgb(220, 250, 230)',
  Alert: 'rgb(250, 250, 200)',
  Emergency: 'rgb(250, 200, 200)',
  'Initializing...': 'rgb(200, 230, 255)',
  Undefined: 'rgb(220, 240, 255)',
}

/** An application unheard for three seconds: greyed out whole, because the
 *  status it shows is the last one known and may no longer be true. */
const STALE_ROW = { background: 'rgb(240, 240, 240)', color: 'rgb(150, 150, 150)' }

function timeOfDay(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString(undefined, {
    hour12: false,
  })
}

export function AppStatusTable({
  apps,
  serverTime,
  variant = 'focused',
}: {
  apps: AppStatusRow[]
  serverTime: number
  /** The dock shows the Qt table's three columns; focused, there is room for
   *  the data time stamp and how long ago the application was last heard. */
  variant?: PanelVariant
}) {
  const compact = variant === 'dashboard'
  return (
    <Table className={tableDensity(variant)}>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Status</TableHead>
          {compact ? (
            <TableHead className="text-right">Time stamp</TableHead>
          ) : (
            <>
              <TableHead className="text-right">Data time</TableHead>
              <TableHead className="text-right">Last heard</TableHead>
            </>
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {apps.map((app) => (
          <TableRow
            key={app.uuid}
            // Inline, so the shared row's hover tint does not replace a colour
            // that carries meaning. The text colour is set with it: these are
            // light backgrounds whatever the page theme is.
            style={
              app.stale
                ? STALE_ROW
                : { background: ROW_BACKGROUND[app.status], color: 'rgb(0, 0, 0)' }
            }
          >
            <TableCell className="font-medium">{app.app_name}</TableCell>
            <TableCell>
              {app.status}
              {app.stale && <span className="ml-2">(stale)</span>}
            </TableCell>
            {compact ? (
              <TableCell className="text-right tabular-nums">
                {timeOfDay(app.received_at)}
              </TableCell>
            ) : (
              <>
                <TableCell className="text-right tabular-nums">
                  {timeOfDay(app.t)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {Math.max(0, serverTime - app.received_at).toFixed(1)}s ago
                </TableCell>
              </>
            )}
          </TableRow>
        ))}
        {apps.length === 0 && (
          <TableRow>
            <TableCell
              colSpan={compact ? 3 : 4}
              className="h-16 text-center text-muted-foreground"
            >
              No applications have reported yet.
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  )
}
