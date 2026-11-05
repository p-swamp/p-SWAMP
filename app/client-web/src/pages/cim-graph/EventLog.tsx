import { useMemo } from 'react'

import type { CimLayout, SimEvent } from './useCimGraphSocket'

/** How many events the log shows, newest first. */
const SHOWN = 8

const KIND: Record<SimEvent['kind'], string> = {
  open: 'opened',
  close: 'closed',
  trip: 'tripped',
  reconnect: 'reconnected',
  short_circuit: 'short circuit',
  clear_short_circuit: 'short circuit cleared',
  load_step: 'load step',
  reset: 'simulation reset',
}

const CAUSE: Record<SimEvent['cause'], string> = {
  command: 'operated',
  disturbance: 'disturbance',
  protection: 'protection',
}

/** Every object of the layout by mRID, for a person: its name. */
function namesOf(layout: CimLayout | null): Map<string, string> {
  const names = new Map<string, string>()
  if (!layout) return names
  for (const s of layout.substations) {
    names.set(s.mrid, s.name)
    for (const node of s.nodes) names.set(node.mrid, `${node.name} (${s.name})`)
  }
  for (const group of [layout.branches, layout.breakers, layout.loads]) for (const x of group) names.set(x.mrid, x.name)
  return names
}

/**
 * What the live simulation announced, newest first: disturbances, and what its protection did about
 * them. The map shows the graph only, and a disturbance never reaches the graph, so this is where a
 * person sees one happen.
 */
export function EventLog({ events, layout }: { events: SimEvent[]; layout: CimLayout | null }) {
  const names = useMemo(() => namesOf(layout), [layout])
  const shown = events.slice(-SHOWN).reverse()
  return (
    <div data-testid="event-log" className="text-xs" aria-live="polite">
      <div className="text-muted-foreground mb-1 font-medium">Simulation events</div>
      {shown.length === 0 ? (
        <div className="text-muted-foreground">None yet. Right-click a line, a substation or a load to disturb it.</div>
      ) : (
        <ol className="space-y-0.5">
          {shown.map((event, i) => (
            <li key={`${event.timestamp}-${event.mRID}-${i}`} data-kind={event.kind} data-cause={event.cause} className="flex gap-2">
              <span className="text-muted-foreground w-16 shrink-0 tabular-nums">t = {event.sim_time.toFixed(2)} s</span>
              <span className="w-20 shrink-0">{CAUSE[event.cause]}</span>
              <span>
                <span className="font-medium">{names.get(event.mRID) ?? event.mRID}</span> {KIND[event.kind]}
                {event.detail && <span className="text-muted-foreground"> · {event.detail}</span>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
