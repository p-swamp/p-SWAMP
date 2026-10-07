import { XIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'

import { Panel } from '../Panel'
import { AlarmDetails } from './AlarmDetails'
import { AlarmView } from './AlarmView'
import { useIslandingData } from './islandingContext'

/**
 * One alarm, opened — the Qt main window's "Alarm details" dock, which sits
 * at the bottom of the window and holds an `AlarmHandlingDialogue`.
 *
 * The same two halves: on the left who raised the alarm, its event log and the
 * operator's actions; on the right the view that belongs to the application
 * that raised it.
 *
 * The alarm is looked up in the live list by id rather than handed in, so the
 * dock keeps up with events landing on it — and renders nothing once the alarm
 * has gone, the store being bounded.
 */
export function AlarmDetailsDock({
  uuid,
  onClose,
}: {
  uuid: string
  onClose: () => void
}) {
  const { state, status, connected, acknowledge, silence, annotate } =
    useIslandingData()
  const alarm = state?.alarms.alarms.find((candidate) => candidate.uuid === uuid)
  if (!alarm) return null

  return (
    <Panel
      title="Alarm details"
      status={status}
      ready={connected}
      fill
      // A dock along the bottom has a height of its own rather than a share of
      // the window's; the grid above it gives up the room.
      className="lg:h-[272px] lg:flex-none"
      contentClassName="overflow-hidden"
      actions={
        <Button
          size="icon-xs"
          variant="ghost"
          aria-label="Close alarm details"
          onClick={onClose}
        >
          <XIcon />
        </Button>
      }
    >
      <div className="flex h-full min-h-0 flex-col gap-3 lg:flex-row">
        <AlarmDetails
          alarm={alarm}
          onAcknowledge={acknowledge}
          onSilence={silence}
          onAnnotate={annotate}
          variant="dashboard"
          className="shrink-0 overflow-y-auto lg:w-[340px]"
        />
        <AlarmView alarm={alarm} />
      </div>
    </Panel>
  )
}
