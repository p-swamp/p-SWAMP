import { BrowserRouter, Navigate, Route, Routes } from 'react-router'

import { AppLayout } from '@/components/AppLayout'
import { BASE_PATH } from '@/lib/basePath'
import { GridMonitorPage } from '@/pages/grid-monitor/GridMonitorPage'
import { AppStatusPanel } from '@/pages/grid-monitor/app-status/AppStatusPanel'
import { IslandingFocused } from '@/pages/grid-monitor/islanding/IslandingFocused'
import { LineOutagePanel } from '@/pages/grid-monitor/line-outage/LineOutagePanel'
import { PhasorsPanel } from '@/pages/grid-monitor/phasors/PhasorsPanel'
import { MeasurementsPanel } from '@/pages/grid-monitor/time-window/MeasurementsPanel'
import { PmuTestStreamerPage } from '@/pages/pmu-test-streamer/PmuTestStreamerPage'
import { ReferenceSubappPage } from '@/pages/reference-subapp/ReferenceSubappPage'
import { RollingFrequencyPage } from '@/pages/rolling-frequency/RollingFrequencyPage'

/**
 * The route table — the one place that knows which apps this client hosts.
 *
 * An app is a folder under `src/pages/<app>/`. Most own a single route; the grid
 * monitor owns several, because its panels are views of one server-side timeline
 * that are useful both together (the dashboard at `/`) and one at a time (the
 * focused routes below, which render the *same* panel components with
 * variant="focused" rather than copies of them).
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
        <Route element={<AppLayout />}>
          <Route index element={<GridMonitorPage />} />

          {/* Full-size views of individual monitor panels. */}
          <Route
            path="time-window"
            element={<MeasurementsPanel variant="focused" />}
          />
          <Route path="phasors" element={<PhasorsPanel variant="focused" />} />
          <Route path="islanding" element={<IslandingFocused />} />
          <Route
            path="line-outage"
            element={<LineOutagePanel variant="focused" />}
          />
          <Route
            path="app-status"
            element={<AppStatusPanel variant="focused" />}
          />

          {/* Scaffold demo, unrelated to the p-SWAMP pipeline. */}
          <Route path="pmu-test-streamer" element={<PmuTestStreamerPage />} />

          <Route path="reference-subapp" element={<ReferenceSubappPage />} />
          <Route path="rolling-frequency" element={<RollingFrequencyPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
