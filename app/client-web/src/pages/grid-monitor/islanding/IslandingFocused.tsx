import { GridViewPanel } from '../grid-view/GridViewPanel'
import { LineOutageData } from '../line-outage/LineOutageData'
import { PhasorsData } from '../phasors/PhasorsData'
import { TimeWindowData } from '../time-window/TimeWindowData'
import { AlarmsPanel } from './AlarmsPanel'
import { IslandingData } from './IslandingData'

/**
 * The full-size islanding view (route `/islanding`).
 *
 * The grid and the alarms, because both come off the one islanding socket —
 * showing the detection without the alarms it raised would be half the story.
 * Renders the same components the main window does, only larger.
 *
 * The other three providers are what the grid view draws from besides: which
 * branches are open, every station's frequency, which is how high each island
 * rides, and the phasors its voltage heat map is made of.
 */
export function IslandingFocused() {
  return (
    <div className="w-full max-w-6xl space-y-4">
      <IslandingData>
        <LineOutageData>
          <TimeWindowData measurement="f">
            <PhasorsData>
              <GridViewPanel variant="focused" />
            </PhasorsData>
          </TimeWindowData>
        </LineOutageData>
        <AlarmsPanel variant="focused" />
      </IslandingData>
    </div>
  )
}
