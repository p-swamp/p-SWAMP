import { useState } from 'react'
import { BellIcon, WifiOffIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'

import { Panel } from '../Panel'
import type { PanelVariant } from '../variant'
import { AlarmDetails } from './AlarmDetails'
import { AlarmTable } from './AlarmTable'
import { useIslandingData } from './islandingContext'

/**
 * The alarm overview — the Qt main window's "Alarms" dock.
 *
 * Reads the same socket as the grid view: alarms are derived from the
 * detector's status, and the server sends both together so a client cannot
 * render them inconsistently.
 *
 * Clicking a row opens that alarm's details. Where they open is the caller's
 * business: the main window hands in `selectedUuid`/`onSelect` and shows them in
 * a dock of their own along the bottom, as Qt does; rendered on its own, this
 * panel keeps the selection itself and unfolds the details beneath the table.
 */
export function AlarmsPanel({
  variant = 'dashboard',
  selectedUuid: controlledUuid,
  onSelect,
  fill,
  className,
}: {
  variant?: PanelVariant
  selectedUuid?: string | null
  onSelect?: (uuid: string | null) => void
  fill?: boolean
  className?: string
}) {
  const { state, status, connected, acknowledge, silence, annotate } = useIslandingData()
  const [ownUuid, setOwnUuid] = useState<string | null>(null)
  const detailsElsewhere = onSelect !== undefined
  const selectedUuid = detailsElsewhere ? (controlledUuid ?? null) : ownUuid

  const alarms = state?.alarms.alarms ?? []
  // Resolved from the live list rather than held in state, so open details keep
  // updating as events land on that alarm. A selection that disappears (the
  // store is bounded) simply closes them.
  const selected = alarms.find((a) => a.uuid === selectedUuid) ?? null
  const unseen = alarms.filter((a) => a.status === 'unseen').length
  const ready = connected && state !== null

  return (
    <Panel
      title="Alarms"
      subtitle="Raised by the monitoring applications"
      status={status}
      ready={ready}
      focusHref="/islanding"
      variant={variant}
      fill={fill}
      className={className}
      minBodyClass="min-h-[160px]"
      contentClassName="p-0"
      badge={
        connected ? (
          <Badge
            variant={unseen > 0 ? 'default' : 'secondary'}
            className={
              unseen > 0
                ? 'border-transparent bg-red-600/20 text-red-700 dark:text-red-400'
                : undefined
            }
          >
            <BellIcon className="size-3" />
            {unseen > 0 ? `${unseen} unseen` : `${alarms.length}`}
          </Badge>
        ) : (
          <Badge variant="outline" className="text-muted-foreground">
            <WifiOffIcon className="size-3" />
            Offline
          </Badge>
        )
      }
    >
      <AlarmTable
        alarms={alarms}
        selectedUuid={selectedUuid}
        onSelect={onSelect ?? setOwnUuid}
        onAcknowledge={acknowledge}
        onSilence={silence}
        variant={variant}
      />

      {selected && !detailsElsewhere && (
        <AlarmDetails
          alarm={selected}
          onAcknowledge={acknowledge}
          onSilence={silence}
          onAnnotate={annotate}
          className="border-t bg-muted/30 px-6 py-4"
        />
      )}
    </Panel>
  )
}
