import { useCallback, useMemo } from 'react'

import { islandColor, islandName, TRACE_COLOR } from '../palette'
import { PhasorDial } from '../phasors/PhasorDial'
import { usePhasorsData } from '../phasors/phasorsContext'
import { TimeWindowChart } from '../time-window/TimeWindowChart'
import { useTimeWindowData } from '../time-window/timeWindowContext'
import type { ChannelInfo } from '../time-window/useTimeWindowSocket'
import { useIslandingData } from './islandingContext'
import type { Alarm } from './useIslandingSocket'

// A constant: the height is a dependency of the effect that builds the plot.
const CHART_HEIGHT = 208

/**
 * The view that goes with an alarm — the right-hand side of the Qt
 * `AlarmHandlingDialogue`, chosen there by which application raised it.
 *
 * For an islanding alarm that is `IslandingAlarmView`: every station's
 * frequency, coloured by the island it is in, beside the voltage phasors
 * coloured the same way — so the split is visible both as a band of traces
 * parting and as a group of phasors swinging away. Any other alarm gets what
 * Qt's default view gives it, the frequencies alone.
 *
 * The alarm's start and end are marked on the time axis, as there.
 *
 * What this does not have is that view's time slider. Qt keeps every sample
 * from just before the alarm and lets an operator scrub back through it; this
 * shows the live window, so an alarm raised more than thirty seconds ago has
 * scrolled out of it.
 */
export function AlarmView({ alarm }: { alarm: Alarm }) {
  const { state } = useIslandingData()
  const { buffer, subscribe, channels } = useTimeWindowData()
  const phasors = usePhasorsData()
  const byIsland = alarm.app_name === 'IslandingApp'

  const islands = state?.islanding?.islands
  const islandOf = useMemo(() => {
    const map = new Map<string, number>()
    for (const island of islands ?? []) {
      island.stations.forEach((station) => map.set(station.trim(), island.index))
    }
    return map
  }, [islands])

  const strokeOf = useCallback(
    (channel: ChannelInfo) =>
      byIsland ? islandColor(islandOf.get(channel.station.trim())) : TRACE_COLOR,
    [byIsland, islandOf],
  )
  const markers = useMemo(
    () => [
      { t: alarm.t_start, label: 'Alarm start' },
      ...(alarm.t_end !== null ? [{ t: alarm.t_end, label: 'Alarm end' }] : []),
    ],
    [alarm.t_start, alarm.t_end],
  )

  return (
    <div className="flex min-w-0 flex-1 items-start gap-2">
      <div className="min-w-0 flex-1">
        <TimeWindowChart
          buffer={buffer}
          subscribe={subscribe}
          channels={channels}
          height={CHART_HEIGHT}
          legend={false}
          strokeOf={strokeOf}
          markers={markers}
          yLabel="f [Hz]"
        />
      </div>
      {byIsland && (
        <>
          <div className="shrink-0">
            <PhasorDial
              phasors={phasors.state?.phasors ?? []}
              magRef={phasors.state?.mag_ref ?? null}
              angRef={phasors.state?.ang_ref ?? null}
              equalLengths
              rotateToMean
              size={CHART_HEIGHT + 8}
            />
          </div>
          <ul className="w-24 shrink-0 space-y-1 text-xs">
            {(islands ?? []).map((island) => (
              <li key={island.index} className="flex items-center gap-1.5">
                <span
                  className="size-2.5 shrink-0 rounded-full ring-1 ring-foreground/20"
                  style={{ background: islandColor(island.index) }}
                />
                {islandName(island.index)}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
