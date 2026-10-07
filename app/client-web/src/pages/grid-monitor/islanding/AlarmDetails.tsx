import { useState } from 'react'

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
import type { Alarm } from './useIslandingSocket'

/**
 * The handling half of an alarm's details — the left-hand column of the Qt
 * `AlarmHandlingDialogue`: who raised it and when, the full event log, and the
 * operator actions.
 *
 * The other half of that dialogue is a view specific to the application that
 * raised the alarm; see `AlarmDetailsDock`, which puts the two side by side.
 */

/**
 * Event row colours, the Qt dialogue's own (`update_message_display`): the
 * raising event is loud, operator actions are muted, and a typed note is
 * visually distinct from both so it reads as human rather than machine.
 */
const EVENT_BACKGROUND: Record<string, string> = {
  init: 'rgb(255, 100, 100)',
  acknowledge: 'rgb(255, 200, 200)',
  not_critical: 'rgb(255, 200, 200)',
  user_message: 'rgb(200, 200, 255)',
  silence: 'rgb(225, 225, 225)',
}

function clockTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString(undefined, {
    hour12: false,
  })
}

export function AlarmDetails({
  alarm,
  onAcknowledge,
  onSilence,
  onAnnotate,
  variant = 'focused',
  className,
}: {
  alarm: Alarm
  onAcknowledge: (uuid: string) => void
  onSilence: (uuid: string) => void
  onAnnotate: (uuid: string, message: string) => void
  variant?: PanelVariant
  className?: string
}) {
  const [note, setNote] = useState('')
  const compact = variant === 'dashboard'

  const submitNote = () => {
    const text = note.trim()
    if (!text) return
    onAnnotate(alarm.uuid, text)
    setNote('')
  }

  return (
    <div className={cn(compact ? 'space-y-2 text-xs' : 'space-y-4', className)}>
      <dl
        className={cn(
          'grid grid-cols-[auto_1fr] gap-x-4',
          compact ? 'gap-y-0.5' : 'gap-y-1 text-sm',
        )}
      >
        <dt className="text-muted-foreground">Detected by</dt>
        <dd className="font-medium">{alarm.app_name}</dd>
        <dt className="text-muted-foreground">Time stamp</dt>
        <dd className="tabular-nums">
          {clockTime(alarm.t_start)}
          {alarm.t_end !== null && <> – {clockTime(alarm.t_end)}</>}
        </dd>
        {!compact && (
          <>
            <dt className="text-muted-foreground">Alarm ID</dt>
            <dd className="font-mono text-xs break-all">{alarm.uuid}</dd>
          </>
        )}
      </dl>

      <div className="overflow-hidden rounded-md border bg-background">
        <Table className={tableDensity(variant)}>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Message</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {alarm.events.map((event, i) => (
              <TableRow
                key={`${event.t}-${i}`}
                style={{
                  background: EVENT_BACKGROUND[event.type],
                  color: 'rgb(0, 0, 0)',
                }}
              >
                <TableCell className="tabular-nums">{clockTime(event.t)}</TableCell>
                <TableCell className="font-mono">{event.type}</TableCell>
                <TableCell className="whitespace-normal">{event.message}</TableCell>
              </TableRow>
            ))}
            {alarm.events.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={3}
                  className="h-12 text-center text-muted-foreground"
                >
                  No events recorded.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex flex-wrap items-center gap-2">
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
        {/* The Qt dialogue asks for the note in a pop-up; a field beside the
            button is the same action without the modal. */}
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submitNote()
          }}
          placeholder="Add a note…"
          aria-label="Annotation"
          className={cn(
            'min-w-24 flex-1 rounded-md border bg-background px-2.5 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
            compact ? 'h-7' : 'h-9 text-sm',
          )}
        />
        <Button size="sm" variant="outline" disabled={!note.trim()} onClick={submitNote}>
          Annotate
        </Button>
      </div>
    </div>
  )
}
