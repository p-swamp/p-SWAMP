import { useMemo } from 'react'
import { WifiOffIcon } from 'lucide-react'

// This page's own pieces, imported relatively so the folder stays self-contained.
import { useCimGraphSocket } from './useCimGraphSocket'
import type { CimLayout, GraphStatus } from './useCimGraphSocket'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { fitProjection } from '@/lib/geoProjection'

const VIEW_W = 640
const VIEW_H = 720
const PAD = 0.15 // degrees of margin around the grid
const OK = '#16a34a'
const OUT = '#ef4444'
const PENDING = '#f59e0b'

/** The status bar's word for where the graph is. */
const GRAPH_STATUS: Record<GraphStatus['kind'], string> = {
  loading: 'loading the grid…',
  ready: 'ready',
  'read-only': 'read-only',
  unavailable: 'not available',
}

/** The bounding box of everything the layout places, with a margin. */
function boundsOf(layout: CimLayout): [number, number, number, number] {
  const points = [
    ...layout.substations.map((s) => s.position),
    ...layout.branches.flatMap((b) => b.path),
  ]
  const lons = points.map((p) => p.lon)
  const lats = points.map((p) => p.lat)
  return [
    Math.min(...lons) - PAD,
    Math.min(...lats) - PAD,
    Math.max(...lons) + PAD,
    Math.max(...lats) + PAD,
  ]
}

/**
 * The CIM graph page (route `/cim-graph`): the grid on its geographic layout, drawn from the graph's
 * own GL profile. Click a breaker to open or close it; click a line to take it out of service or
 * bring it back (its bay breakers, or its terminals where it has no breaker). The running grid
 * simulation follows the graph, so the PMU test streamer's rtsim source shows the result.
 *
 * Hand-drawn SVG, like the islanding map: a few hundred elements, no map library. The graph is
 * shared, so this page, any other open page and the simulation always agree. What was clicked shows
 * as switching (amber) until the server's state shows it done; the status bar under the map says
 * where the graph is, when it last changed and how long the last click took to come back.
 */
export function CimGraphPage() {
  const { state, layout, status, connected, graph, error, pending, roundTripMs, changedAt, setSwitch, setLine, reset } =
    useCimGraphSocket()

  const drawing = useMemo(() => {
    if (!layout || layout.substations.length === 0) return null
    const project = fitProjection(boundsOf(layout), VIEW_W, VIEW_H)
    const at = new Map(layout.substations.map((s) => [s.mrid, project(s.position.lon, s.position.lat)]))
    const branches = layout.branches.flatMap((b) => {
      const a = at.get(b.from_substation)
      const z = at.get(b.to_substation)
      if (!a || !z) return []
      const points =
        b.path.length >= 2
          ? b.path.map((p) => project(p.lon, p.lat))
          : [a, z]
      return [{ ...b, d: points.map(([x, y]) => `${x},${y}`).join(' ') }]
    })
    // Breakers stand in a small ring around their substation.
    const perStation = new Map<string, number>()
    layout.breakers.forEach((b) => perStation.set(b.substation, (perStation.get(b.substation) ?? 0) + 1))
    const seen = new Map<string, number>()
    const breakers = layout.breakers.flatMap((b) => {
      const centre = at.get(b.substation)
      if (!centre) return []
      const i = seen.get(b.substation) ?? 0
      seen.set(b.substation, i + 1)
      const count = perStation.get(b.substation) ?? 1
      const angle = (2 * Math.PI * i) / count
      // a ring wide enough that neighbours do not cover each other (a marker is 8 wide): a
      // substation with many breakers gets a wider ring
      const radius = Math.max(12, (count * 11) / (2 * Math.PI))
      return [{ ...b, x: centre[0] + radius * Math.cos(angle), y: centre[1] + radius * Math.sin(angle) }]
    })
    const names = new Map(layout.substations.map((s) => [s.mrid, s.name]))
    const breakerNames = new Map(layout.breakers.map((b) => [b.mrid, b.name]))
    return { at, branches, breakers, names, breakerNames, perStation }
  }, [layout])

  const out = useMemo(() => new Set(state?.out_of_service ?? []), [state])

  /** Click a line. The layout already says which breaker takes it out on its own, so taking it out is
   *  that one breaker, and bringing it back is closing it (or, if it was put out some other way, or has
   *  no breaker, the server's line command, which undoes whatever put it out). */
  const operate = (line: CimLayout['branches'][number], isOut: boolean) => {
    if (!isOut && line.breaker) setSwitch(line.breaker, true)
    else if (isOut && line.breaker && state?.switches[line.breaker]) setSwitch(line.breaker, false)
    else setLine(line.mrid, !isOut)
  }
  const openCount = state ? Object.values(state.switches).filter(Boolean).length : 0
  const editable = connected && !!state?.writable
  const isPending = (line: CimLayout['branches'][number]) =>
    pending.has(line.mrid) || (!!line.breaker && pending.has(line.breaker))

  return (
    <Card className="w-full gap-0">
      <CardHeader className="border-b">
        <CardTitle className="text-lg">CIM graph</CardTitle>
        <span className="text-muted-foreground text-sm">
          The grid as the CIM graph describes it. Click a breaker or a line to switch it: the graph is
          shared, and the grid simulation follows it.
        </span>
        <CardAction className="flex items-center gap-2 self-center">
          {state && (
            <Badge variant="outline">
              {openCount} open · {out.size} out of service
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
        {state && !state.writable && (
          <Alert>
            <AlertTitle>The graph is read-only</AlertTitle>
            <AlertDescription>
              The CGMES profiles are not loaded, so breakers cannot be switched from here.
            </AlertDescription>
          </Alert>
        )}

        {graph.kind === 'unavailable' && (
          <Alert variant="destructive">
            <AlertTitle>The grid is not available</AlertTitle>
            <AlertDescription>{graph.reason}</AlertDescription>
          </Alert>
        )}

        {!drawing || !state ? (
          <div className="text-muted-foreground flex h-64 items-center justify-center text-sm">
            {graph.kind === 'unavailable'
              ? 'No grid to draw.'
              : status.kind === 'online' || graph.kind === 'loading'
                ? 'Loading the grid into the CIM graph…'
                : status.label}
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
            className="h-[70vh] w-full"
            role="img"
            aria-label="The grid on its geographic layout"
          >
            {drawing.branches.map((b) => {
              const isOut = out.has(b.mrid)
              const switching = isPending(b)
              const ends = `${drawing.names.get(b.from_substation) ?? '?'} to ${drawing.names.get(b.to_substation) ?? '?'}`
              const via = b.breaker
                ? `operated by ${drawing.breakerNames.get(b.breaker) ?? b.breaker}`
                : 'no breaker of its own'
              return (
                <g
                  key={b.mrid}
                  data-testid={`line-${b.name}`}
                  data-out={isOut}
                  data-pending={switching}
                  className={editable ? 'cursor-pointer' : undefined}
                  onClick={() => editable && operate(b, isOut)}
                >
                  <title>
                    {`${b.name} (${b.kind}, ${ends}): ${isOut ? 'out of service' : 'in service'}, ${via}${switching ? ' · switching…' : ''}`}
                  </title>
                  {/* a wide invisible stroke: the line itself is too thin to click */}
                  <polyline points={b.d} fill="none" stroke="transparent" strokeWidth={10} />
                  <polyline
                    points={b.d}
                    fill="none"
                    stroke={switching ? PENDING : isOut ? OUT : OK}
                    strokeWidth={isOut || switching ? 2 : 1.5}
                    strokeDasharray={isOut ? '5 4' : undefined}
                    opacity={isOut || switching ? 0.95 : 0.6}
                    className={switching ? 'animate-pulse' : undefined}
                  />
                </g>
              )
            })}

            {layout?.substations.map((s) => {
              const point = drawing.at.get(s.mrid)
              if (!point) return null
              return (
                <g key={s.mrid}>
                  <title>{`${s.name} (substation, ${drawing.perStation.get(s.mrid) ?? 0} breakers drawn)`}</title>
                  <circle cx={point[0]} cy={point[1]} r={3.5} fill="#334155" />
                  <text x={point[0] + 6} y={point[1] - 6} fontSize={9} className="fill-muted-foreground">
                    {s.name}
                  </text>
                </g>
              )
            })}

            {drawing.breakers.map((b) => {
              const isOpen = state.switches[b.mrid] ?? false
              const switching = pending.has(b.mrid)
              return (
                <g
                  key={b.mrid}
                  data-testid={`breaker-${b.name}`}
                  data-open={isOpen}
                  data-pending={switching}
                  className={editable ? 'cursor-pointer' : undefined}
                  onClick={() => editable && setSwitch(b.mrid, !isOpen)}
                >
                  <title>
                    {`${b.name} (breaker, ${drawing.names.get(b.substation) ?? b.substation}): ${isOpen ? 'open' : 'closed'}${switching ? ' · switching…' : ''}`}
                  </title>
                  <rect
                    x={b.x - 4}
                    y={b.y - 4}
                    width={8}
                    height={8}
                    fill={isOpen ? 'transparent' : OK}
                    stroke={switching ? PENDING : isOpen ? OUT : OK}
                    strokeWidth={switching ? 2.5 : 1.5}
                    className={switching ? 'animate-pulse' : undefined}
                  />
                </g>
              )
            })}
          </svg>
        )}

        <div className="text-muted-foreground flex flex-wrap gap-4 text-xs">
          <span>
            <span className="mr-1 inline-block h-0.5 w-5 align-middle" style={{ background: OK }} />
            in service
          </span>
          <span>
            <span
              className="mr-1 inline-block h-0.5 w-5 align-middle"
              style={{ background: `repeating-linear-gradient(90deg, ${OUT} 0 5px, transparent 5px 9px)` }}
            />
            out of service
          </span>
          <span>
            <span className="mr-1 inline-block size-2 align-middle" style={{ background: OK }} />
            breaker closed
          </span>
          <span>
            <span
              className="mr-1 inline-block size-2 border align-middle"
              style={{ borderColor: OUT }}
            />
            breaker open
          </span>
          <span>
            <span className="mr-1 inline-block size-2 border-2 align-middle" style={{ borderColor: PENDING }} />
            switching (clicked, not yet in the graph)
          </span>
          <span>hover anything for its name</span>
        </div>

        <div
          data-testid="cim-status"
          className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 border-t pt-2 text-xs"
        >
          <span>Connection: {status.kind === 'online' ? 'online' : status.kind === 'connecting' ? 'connecting…' : 'offline'}</span>
          <span>Graph: {GRAPH_STATUS[graph.kind]}</span>
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
