import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

import { type PanelVariant, tableDensity } from '../variant'
import type { Alarm, AlarmStatus } from './useIslandingSocket'

/**
 * Row colours, the Qt alarm overview's own (`AlarmOverview.update_display`): an
 * unseen alarm is loud, one that has been handled or has cleared is quiet, a
 * silenced one is greyed out. The whole row is tinted, as there.
 */
const ROW_BACKGROUND: Record<AlarmStatus, string> = {
  unseen: 'rgb(250, 100, 100)',
  acknowledged: 'rgb(255, 200, 200)',
  not_critical: 'rgb(255, 200, 200)',
  silenced: 'rgb(225, 225, 225)',
}

const STATUS_LABELS: Record<AlarmStatus, string> = {
  unseen: 'Unseen',
  acknowledged: 'Acknowledged',
  not_critical: 'Cleared',
  silenced: 'Silenced',
}

function clockTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString(undefined, {
    hour12: false,
  })
}

export function AlarmTable({
  alarms,
  selectedUuid,
  onSelect,
  onAcknowledge,
  onSilence,
  variant = 'focused',
}: {
  alarms: Alarm[]
  /** The alarm whose details are open, if any. */
  selectedUuid?: string | null
  /** Toggles the details. Passing null closes them. */
  onSelect?: (uuid: string | null) => void
  onAcknowledge: (uuid: string) => void
  onSilence: (uuid: string) => void
  /** The dock shows the Qt table's three columns and leaves the operator
   *  actions to the details it opens; focused, they are on the row too. */
  variant?: PanelVariant
}) {
  const compact = variant === 'dashboard'
  const columns = compact ? 3 : 4
  return (
    <Table className={tableDensity(variant)}>
      <TableHeader>
        <TableRow>
          <TableHead>Time</TableHead>
          <TableHead>App</TableHead>
          <TableHead>Alarm status</TableHead>
          {!compact && <TableHead className="text-right">Actions</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {alarms.map((alarm) => (
          <TableRow
            key={alarm.uuid}
            aria-selected={selectedUuid === alarm.uuid}
            className={cn(
              onSelect && 'cursor-pointer',
              // An inset bar rather than a background: the background is the
              // alarm's status and has to stay readable on the selected row.
              selectedUuid === alarm.uuid && 'shadow-[inset_4px_0_0_0_rgb(0,0,0)]',
            )}
            // Inline, so the shared row's hover tint does not replace a colour
            // that carries meaning; and with its own text colour, since these
            // are light backgrounds whatever the page theme is.
            style={{ background: ROW_BACKGROUND[alarm.status], color: 'rgb(0, 0, 0)' }}
            onClick={
              onSelect
                ? () => onSelect(selectedUuid === alarm.uuid ? null : alarm.uuid)
                : undefined
            }
          >
            <TableCell className="tabular-nums">
              {clockTime(alarm.t_start)}
              {alarm.t_end !== null && <> – {clockTime(alarm.t_end)}</>}
            </TableCell>
            <TableCell className="font-medium">{alarm.app_name}</TableCell>
            <TableCell>{STATUS_LABELS[alarm.status]}</TableCell>
            {!compact && (
              <TableCell
                className="space-x-2 text-right"
                onClick={(e) => e.stopPropagation()}
              >
                <Button
                  size="sm"
                  variant="outline"
                  disabled={alarm.status !== 'unseen'}
                  onClick={() => onAcknowledge(alarm.uuid)}
                >
                  Acknowledge
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={alarm.status === 'silenced'}
                  onClick={() => onSilence(alarm.uuid)}
                >
                  Silence
                </Button>
              </TableCell>
            )}
          </TableRow>
        ))}
        {alarms.length === 0 && (
          <TableRow>
            <TableCell
              colSpan={columns}
              className="h-16 text-center text-muted-foreground"
            >
              No alarms raised.
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  )
}
