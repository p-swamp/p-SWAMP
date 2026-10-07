import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { AppLayout } from '@/components/AppLayout'
import { BASE_PATH } from '@/lib/basePath'
import { GridMonitorPage } from '@/pages/grid-monitor/GridMonitorPage'
import { AppStatusPanel } from '@/pages/grid-monitor/app-status/AppStatusPanel'
import { IslandingFocused } from '@/pages/grid-monitor/islanding/IslandingFocused'
import { LineOutageData } from '@/pages/grid-monitor/line-outage/LineOutageData'
import { LineOutagePanel } from '@/pages/grid-monitor/line-outage/LineOutagePanel'
import { PhasorsData } from '@/pages/grid-monitor/phasors/PhasorsData'
import { PhasorsPanel } from '@/pages/grid-monitor/phasors/PhasorsPanel'
import { MeasurementsPanel } from '@/pages/grid-monitor/time-window/MeasurementsPanel'
import { PmuTestStreamerPage } from '@/pages/pmu-test-streamer/PmuTestStreamerPage'
import { ReferenceSubappPage } from '@/pages/reference-subapp/ReferenceSubappPage'

/**
 * The route table — the one place that knows which apps this client hosts.
 *
 * An app is a folder under `src/pages/<app>/`. Most own a single route; the grid
 * monitor owns several, because its panels are views of one server-side timeline
 * that are useful both together (the main window at `/`) and one at a time (the
 * focused routes below, which render the *same* panel components with
 * variant="focused" rather than copies of them).
 *
 * The monitor is also the one page laid out as a window, filling the viewport
 * and scrolling inside its docks, which is why it sits under a layout route of
 * its own. A panel that shares its socket with another view reads it from a
 * provider, so its focused route mounts that provider around it.
 *
 * Deep links and hard refreshes work in both modes: Vite's dev server and the
 * Python server's SPAStaticFiles both fall back to index.html on an unknown
 * path. Because that fallback catches *any* such path, the `*` route below is
 * what keeps a typo'd URL from rendering the nav over an empty outlet.
 *
 * `basename` is what makes every route below relative to wherever the app is
 * mounted — `/` locally, `/p-swamp` behind the remote reverse
 * proxy — so the paths here (and every `<NavLink to>` / `<Navigate to>`) stay
 * written as if the app owned the origin root. BASE_PATH is discovered at
 * runtime, not configured; see src/lib/basePath.ts.
 */
function App() {
  return (
    <BrowserRouter basename={BASE_PATH || '/'}>
      <Routes>
        <Route element={<AppLayout window />}>
          <Route index element={<GridMonitorPage />} />
        </Route>

        <Route element={<AppLayout />}>
          {/* Full-size views of individual monitor panels. */}
          <Route
            path="time-window"
            element={<MeasurementsPanel variant="focused" />}
          />
          <Route
            path="phasors"
            element={
              <PhasorsData>
                <PhasorsPanel variant="focused" />
              </PhasorsData>
            }
          />
          <Route path="islanding" element={<IslandingFocused />} />
          <Route
            path="line-outage"
            element={
              <LineOutageData>
                <LineOutagePanel variant="focused" />
              </LineOutageData>
            }
          />
          <Route
            path="app-status"
            element={<AppStatusPanel variant="focused" />}
          />

          {/* Scaffold demo, unrelated to the p-SWAMP pipeline. */}
          <Route path="pmu-test-streamer" element={<PmuTestStreamerPage />} />

          <Route path="reference-subapp" element={<ReferenceSubappPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
