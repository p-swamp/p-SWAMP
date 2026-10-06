import { Link } from 'react-router'

import { Button } from '@/components/ui/button'

import { Panel } from './Panel'

/**
 * The applications that have a view of their own. Each entry is a route in
 * App.tsx rendering one of the monitor's panels full-size.
 */
const APPS = [
  { to: '/time-window', label: 'Time window plot' },
  { to: '/phasors', label: 'Voltage phasor plot' },
  { to: '/islanding', label: 'Islanding detection' },
  { to: '/line-outage', label: 'Line outage detection' },
  { to: '/app-status', label: 'Application status' },
]

/**
 * The launcher — the Qt main window's "Apps" dock.
 *
 * There a button starts an application as a process of its own; here the
 * monitoring applications are already running, one set per browser, started by
 * the server when it connected. So a button opens the application's view rather
 * than the application, which is the half of launching that is left.
 *
 * Only what exists is listed. The Qt launcher's FFT and mode-estimation buttons
 * have no counterpart here yet, and a button that does nothing has no place on
 * a monitoring screen.
 */
export function AppsPanel() {
  return (
    <Panel title="Apps">
      <div className="grid grid-cols-2 gap-1.5">
        {APPS.map((app) => (
          <Button key={app.to} asChild size="xs" variant="outline">
            <Link to={app.to}>{app.label}</Link>
          </Button>
        ))}
      </div>
    </Panel>
  )
}
