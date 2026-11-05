import { useCallback, useMemo, useState } from 'react'
import { WifiOffIcon } from 'lucide-react'

// This page's own pieces, imported relatively so the folder stays self-contained.
import { DisturbanceMenu } from './DisturbanceMenu'
import { EventLog } from './EventLog'
import { GridMap } from './GridMap'
import type { MenuRequest, MenuTarget } from './GridMap'
import { DetailPanel } from './DetailPanel'
import { loadingColor, stationColor } from './colors'
import { LiveChart } from './LiveChart'
import { SystemTotals } from './SystemTotals'
import { useCimGraphSocket } from './useCimGraphSocket'
import type { CimLayout, GraphStatus } from './useCimGraphSocket'
import { useLiveFeed, WINDOW_S } from './useLiveFeed'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

/** The status bar's word for where the graph is. */
const GRAPH_STATUS: Record<GraphStatus['kind'], string> = {
  loading: 'loading the grid…',
  ready: 'ready',
  'read-only': 'read-only',
  unavailable: 'not available',
}

/**
 * The grid page (route `/cim-graph`): the grid of the CIM graph on OpenStreetMap, and the live grid
 * simulation that follows it, plotted. Click a breaker to operate it: a command to the simulation,
 * which the graph (and so the map) shows once the simulation has done it. Click a line, a substation
 * or a load to select it: a panel beside the map shows what the graph says of it, its live values and
 * charts, and operates or disturbs it. Right-click (or long-press) one for its disturbances: the
 * simulation only, so the map does not change, and the event log says what happened. A substation
 * clicked, or a station below the charts, is picked out on the charts. The charts show every PMU station's frequency and voltage
 * over the last 30 s, every frame of the simulation (`/api/cim-live`); the status bar says how many
 * reach this page each second.
 */
export function CimGraphPage() {
  const { state, layout, status, connected, graph, error, pending, roundTripMs, changedAt, setSwitch, setLine, reset, disturb, events } =
    useCimGraphSocket()
  const [menu, setMenu] = useState<MenuRequest | null>(null)
  const [selected, setSelected] = useState<MenuTarget | null>(null)
  const closePanel = useCallback(() => setSelected(null), [])
  const closeMenu = useCallback(() => setMenu(null), [])
  const live = useLiveFeed()
  const [highlight, setHighlight] = useState<number | null>(null) // a station's index in the feed

  /** A substation clicked on the map picks its highest-voltage station (or none, off the map's markers). */
  const pickSubstation = (mrid: string | null) => {
    let best: number | null = null
    live.stations.forEach((station, i) => {
      if (mrid === null || station.substation !== mrid) return
      if (best === null || (station.kv ?? 0) > (live.stations[best].kv ?? 0)) best = i
    })
    setHighlight(best)
  }
  const picked = highlight === null ? null : (live.stations[highlight]?.substation ?? null)
  const stationNames = useMemo(() => live.stations.map((s) => s.name), [live.stations])

  /** Click a line. The layout already says which breaker takes it out on its own, so taking it out is
   *  that one breaker, and bringing it back is closing it (or, if it was put out some other way, or has
   *  no breaker, the server's line command, which undoes whatever put it out). */
  const operate = (line: CimLayout['branches'][number], isOut: boolean) => {
    if (!isOut && line.breaker) setSwitch(line.breaker, true)
    else if (isOut && line.breaker && state?.switches[line.breaker]) setSwitch(line.breaker, false)
    else setLine(line.mrid, !isOut)
  }
  const out = state?.out_of_service.length ?? 0
  const openCount = state ? Object.values(state.switches).filter(Boolean).length : 0
  const editable = connected && !!state?.writable

  return (
    <Card className="w-full gap-0">
      <CardHeader className="border-b">
        <CardTitle className="text-lg">Grid</CardTitle>
        <span className="text-muted-foreground text-sm">
          The grid as the CIM graph describes it, and its live simulation. Click a breaker to operate it; click
          a line, a substation or a load to see it and act on it; right-click one to disturb the simulation.
        </span>
        <CardAction className="flex items-center gap-2 self-center">
          {state && (
            <Badge variant="outline">
              {openCount} open · {out} out of service
            </Badge>
          )}
          {connected ? (
            <Badge variant="default">Online</Badge>
          ) : (
            <Badge variant="outline" className="text-muted-foreground">
              <WifiOffIcon className="size-3" />
              Offline
            </Badge>
          )}
          <Button size="sm" variant="outline" disabled={!editable} onClick={reset}>
            Reset grid
          </Button>
        </CardAction>
      </CardHeader>

      <CardContent className="space-y-3 px-6 py-4">
        {error && (
          <Alert variant="destructive">
            <AlertTitle>Not applied</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {graph.kind === 'unavailable' && (
          <Alert variant="destructive">
            <AlertTitle>The grid is not available</AlertTitle>
            <AlertDescription>{graph.reason}</AlertDescription>
          </Alert>
        )}
        {state && !state.writable && (
          <Alert>
            <AlertTitle>The graph is read-only</AlertTitle>
            <AlertDescription>The CGMES profiles are not loaded, so breakers cannot be switched from here.</AlertDescription>
          </Alert>
        )}

        {!layout || !state ? (
          <div className="text-muted-foreground flex h-64 items-center justify-center text-sm">
            {graph.kind === 'unavailable'
              ? 'No grid to draw.'
              : status.kind === 'online' || graph.kind === 'loading'
                ? 'Loading the grid into the CIM graph…'
                : status.label}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1fr_24rem]">
            <div className="relative">
              <GridMap
                layout={layout}
                state={state}
                pending={pending}
                editable={editable}
                onBreaker={(mrid, isOpen) => setSwitch(mrid, !isOpen)}
                onSelect={setSelected}
                selected={selectedMrid(selected)}
                stations={live.stations}
                lineEnds={live.lineEnds}
                buffer={live.buffer}
                subscribe={live.subscribe}
                highlight={picked}
                onPick={pickSubstation}
                onMenu={setMenu}
              />
              {menu && <DisturbanceMenu request={menu} disturb={disturb} onClose={closeMenu} />}
            </div>
            {selected && (
              <DetailPanel
                target={selected}
                layout={layout}
                state={state}
                pending={pending}
                editable={editable}
                live={live}
                disturb={disturb}
                onOperate={operate}
                onBreaker={(mrid, isOpen) => setSwitch(mrid, !isOpen)}
                onClose={closePanel}
              />
            )}
          </div>
        )}

        <div className="text-muted-foreground flex flex-wrap gap-4 text-xs">
          <span>
            <span className="mr-1 inline-block h-0.5 w-5 align-middle" style={{ background: '#16a34a' }} />
            in service
          </span>
          <span>
            <span
              className="mr-1 inline-block h-0.5 w-5 align-middle"
              style={{ background: 'repeating-linear-gradient(90deg, #ef4444 0 5px, transparent 5px 9px)' }}
            />
            out of service
          </span>
          <span>
            loading:{' '}
            {[0.3, 0.6, 0.9, 1].map((x) => (
              <span key={x} className="mr-0.5 inline-block h-1 w-3 align-middle" style={{ background: loadingColor(x) }} />
            ))}{' '}
            under 50 %, 80 %, 100 %, over its limit
          </span>
          <span>
            <span className="mr-1 inline-block size-2 align-middle" style={{ background: '#16a34a' }} />
            breaker closed
          </span>
          <span>
            <span className="mr-1 inline-block size-2 border align-middle" style={{ borderColor: '#ef4444' }} />
            breaker open
          </span>
          <span>
            <span className="mr-1 inline-block size-2 border-2 align-middle" style={{ borderColor: '#f59e0b' }} />
            switching (clicked, not yet in the graph)
          </span>
          <span>
            <svg className="mr-1 inline-block align-middle" width="16" height="10" viewBox="0 0 20 12" aria-hidden="true">
              <circle cx="6" cy="6" r="5" fill="none" stroke="#16a34a" strokeWidth="2" />
              <circle cx="14" cy="6" r="5" fill="none" stroke="#16a34a" strokeWidth="2" />
            </svg>
            transformer
          </span>
          <span>
            <span
              className="mr-1 inline-block align-middle"
              style={{ borderLeft: '4px solid transparent', borderRight: '4px solid transparent', borderTop: '7px solid #7c3aed' }}
            />
            load
          </span>
          <span>substation: blue below 50 Hz, red above</span>
        </div>

        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          <LiveChart
            title={`Frequency (last ${WINDOW_S} s)`}
            unit="Hz"
            quantity="f"
            labels={stationNames}
            buffer={live.buffer}
            subscribe={live.subscribe}
            highlight={highlight}
          />
          <LiveChart
            title={`Voltage (last ${WINDOW_S} s)`}
            unit="p.u."
            quantity="v"
            labels={stationNames}
            buffer={live.buffer}
            subscribe={live.subscribe}
            highlight={highlight}
          />
        </div>

        <div className="flex flex-wrap gap-1 text-xs" role="group" aria-label="Stations">
          {live.stations.map((station, i) => (
            <button
              key={station.name}
              type="button"
              className={`rounded border px-2 py-0.5 ${i === highlight ? 'font-semibold' : ''}`}
              style={{ borderColor: stationColor(i) }}
              aria-pressed={i === highlight}
              onClick={() => setHighlight(i === highlight ? null : i)}
            >
              {station.name}
            </button>
          ))}
        </div>

        <div
          data-testid="cim-status"
          className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 border-t pt-2 text-xs"
        >
          <span>Connection: {status.kind === 'online' ? 'online' : status.kind === 'connecting' ? 'connecting…' : 'offline'}</span>
          <span>Graph: {GRAPH_STATUS[graph.kind]}</span>
          <span data-testid="samples-per-second">
            Simulation: {live.connected ? `${live.samplesPerSecond.toFixed(0)} samples/s` : 'not connected'}
          </span>
          <SystemTotals injections={live.injections} buffer={live.buffer} subscribe={live.subscribe} />
          <span>Last change: {changedAt ? changedAt.toLocaleTimeString() : 'none since this page opened'}</span>
          <span>
            Last click: {roundTripMs === null ? 'none yet' : `${roundTripMs} ms from click to screen`}
            {pending.size > 0 && ` · ${pending.size} switching`}
          </span>
        </div>
        <EventLog events={events} layout={layout} />
      </CardContent>
    </Card>
  )
}

/** The mRID of what is selected, which the map draws as such. */
function selectedMrid(target: MenuTarget | null): string | null {
  if (!target) return null
  return target.kind === 'branch' ? target.branch.mrid : target.kind === 'substation' ? target.substation.mrid : target.load.mrid
}
