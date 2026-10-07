import { useState } from 'react'

import { AppsPanel } from './AppsPanel'
import { PortCaveat } from './PortCaveat'
import { AppStatusPanel } from './app-status/AppStatusPanel'
import { GridViewPanel } from './grid-view/GridViewPanel'
import { AlarmDetailsDock } from './islanding/AlarmDetailsDock'
import { AlarmsPanel } from './islanding/AlarmsPanel'
import { IslandingData } from './islanding/IslandingData'
import { LineOutageData } from './line-outage/LineOutageData'
import { LineOutagePanel } from './line-outage/LineOutagePanel'
import { PhasorsData } from './phasors/PhasorsData'
import { PhasorsPanel } from './phasors/PhasorsPanel'
import { FrequencyPanel } from './time-window/FrequencyPanel'
import { TimeWindowData } from './time-window/TimeWindowData'

/**
 * The grid monitor (route `/`) — p-SWAMP's main window.
 *
 * Laid out as the Qt one is (`gui/main_window.py`): the grid view is the central
 * widget and takes whatever room there is, a column of docks runs down its
 * right — apps, frequency, status, alarms — and clicking an alarm opens its
 * details in a dock beneath the grid. The phasor and line-outage docks are this
 * client's additions; in Qt the first is a layer and a separate window, and the
 * second a layer only.
 *
 * These are not loosely related pages: they are views of a *single* server-side
 * timeline. One replay of the recording drives one measurement window and one
 * islanding detector, so every dock here is showing the same instant — and the
 * thing worth watching is a disturbance arriving in all of them at once.
 *
 * Five sockets feed it, each at its own natural rate — the measurement window
 * at 10 Hz, phasors at 5 Hz, islanding and line outages on events, status at
 * 2 Hz — so a slow or broken one degrades alone. Four of them are opened by the
 * providers below rather than by a panel, because more than one view reads each:
 * the grid view alone draws from three. A provider re-renders only the views
 * that read *it*, which is what keeps one socket's tick from re-rendering the
 * window.
 *
 * Every dock also has a full-size route of its own, rendering the same component
 * with variant="focused"; the expand icon in its title bar links to it.
 */
export function GridMonitorPage() {
  const [alarmUuid, setAlarmUuid] = useState<string | null>(null)

  return (
    <IslandingData>
      <LineOutageData>
        <PhasorsData>
          <TimeWindowData measurement="f">
            {/* From `lg` up this is a window: it has the viewport's height and
                everything scrolls inside its own dock. Below that there is no
                room for a window, so the docks stack and the page scrolls. */}
            <div className="flex w-full min-w-0 flex-1 flex-col gap-1.5 p-1.5 lg:min-h-0">
              <PortCaveat />

              <div className="flex min-w-0 flex-1 flex-col gap-1.5 lg:min-h-0 lg:flex-row">
                {/* The alarm details sit under the grid view only, not under
                    the docks as well: the alarm list that opened them stays
                    where it was, in view, with its selection showing. */}
                <div className="flex min-w-0 flex-1 flex-col gap-1.5 lg:min-h-0">
                  <GridViewPanel variant="dashboard" />
                  {alarmUuid && (
                    <AlarmDetailsDock
                      uuid={alarmUuid}
                      onClose={() => setAlarmUuid(null)}
                    />
                  )}
                </div>

                <aside className="flex shrink-0 flex-col gap-1.5 lg:w-[420px] lg:overflow-y-auto">
                  <AppsPanel />
                  <FrequencyPanel variant="dashboard" />
                  <AppStatusPanel variant="dashboard" />
                  <AlarmsPanel
                    variant="dashboard"
                    selectedUuid={alarmUuid}
                    onSelect={setAlarmUuid}
                    fill
                    className="min-h-[124px]"
                  />
                  <PhasorsPanel variant="dashboard" />
                  <LineOutagePanel variant="dashboard" />
                </aside>
              </div>
            </div>
          </TimeWindowData>
        </PhasorsData>
      </LineOutageData>
    </IslandingData>
  )
}
