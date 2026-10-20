import { useState } from 'react'
import { WifiOffIcon } from 'lucide-react'

// This page's own pieces, imported relatively so the folder stays self-contained.
import { GridMap } from './GridMap'
import { stationColor } from './colors'
import { LiveChart } from './LiveChart'
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
 * simulation that follows it, plotted. Click a breaker or a line to switch it (the graph is shared, and
 * the simulation follows it within a second or two); click a substation, or a station below the
 * charts, to pick it out on the charts. The charts show every PMU station's frequency and voltage
 * over the last 30 s, every frame of the simulation (`/api/cim-live`); the status bar says how many
 * reach this page each second.
 */
export function CimGraphPage() {
  const { state, layout, status, connected, graph, error, pending, roundTripMs, changedAt, setSwitch, setLine, reset } =
    useCimGraphSocket()
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
          The grid as the CIM graph describes it, and its live simulation. Click a breaker or a line to switch
          it; click a substation to pick it out on the charts.
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
          <GridMap
            layout={layout}
            state={state}
            pending={pending}
            editable={editable}
            onBreaker={(mrid, isOpen) => setSwitch(mrid, !isOpen)}
            onLine={operate}
            stations={live.stations}
            buffer={live.buffer}
            subscribe={live.subscribe}
            highlight={picked}
            onPick={pickSubstation}
          />
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
          <span>substation: blue below 50 Hz, red above</span>
        </div>

        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          <LiveChart
            title={`Frequency (last ${WINDOW_S} s)`}
            unit="Hz"
            quantity="f"
            stations={live.stations}
            buffer={live.buffer}
            subscribe={live.subscribe}
            highlight={highlight}
          />
          <LiveChart
            title={`Voltage (last ${WINDOW_S} s)`}
            unit="p.u."
            quantity="v"
            stations={live.stations}
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
          <span>Last change: {changedAt ? changedAt.toLocaleTimeString() : 'none since this page opened'}</span>
          <span>
            Last click: {roundTripMs === null ? 'none yet' : `${roundTripMs} ms from click to screen`}
            {pending.size > 0 && ` · ${pending.size} switching`}
          </span>
        </div>
      </CardContent>
    </Card>
  )
}
