import { useEffect, useMemo, useRef } from 'react'
import { XIcon } from 'lucide-react'

import { disturbancesOf } from './disturbances'
import type { Disturb } from './disturbances'
import type { MenuTarget } from './GridMap'
import { LiveChart } from './LiveChart'
import type { CimGraphState, CimLayout } from './useCimGraphSocket'
import type { LiveBuffer, LiveInjection, LiveLineEnd, LiveStation } from './useLiveFeed'
import { Button } from '@/components/ui/button'

/** How often the live values are rewritten: a reader need not follow 50 frames a second. */
const EVERY_MS = 250

type Live = {
  stations: LiveStation[]
  lineEnds: LiveLineEnd[]
  injections: LiveInjection[]
  buffer: React.RefObject<LiveBuffer>
  subscribe: (listener: () => void) => () => void
}

/** One live value: a label, and how to read its text off the buffer. */
type Reading = { label: string; read: (buffer: LiveBuffer) => string }

const newest = (series: (number | null)[] | undefined) => series?.[series.length - 1] ?? null
const fixed = (x: number | null, digits: number, unit: string) => (x === null ? '—' : `${x.toFixed(digits)} ${unit}`)

/** The live values of the selection, written into the DOM from the buffer, never through a render. */
function LiveValues({ readings, buffer, subscribe }: { readings: Reading[]; buffer: React.RefObject<LiveBuffer>; subscribe: Live['subscribe'] }) {
  const cells = useRef<(HTMLElement | null)[]>([])
  useEffect(() => {
    let last = 0
    return subscribe(() => {
      const now = performance.now()
      if (now - last < EVERY_MS) return
      last = now
      readings.forEach((reading, i) => {
        const cell = cells.current[i]
        if (cell) cell.textContent = reading.read(buffer.current)
      })
    })
  }, [buffer, readings, subscribe])
  if (readings.length === 0) return <p className="text-muted-foreground text-xs">The simulation measures nothing here.</p>
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs" data-testid="detail-live">
      {readings.map((reading, i) => (
        <div key={reading.label} className="contents">
          <dt className="text-muted-foreground">{reading.label}</dt>
          <dd
            className="tabular-nums"
            ref={(cell) => {
              cells.current[i] = cell
            }}
          >
            —
          </dd>
        </div>
      ))}
    </dl>
  )
}

type Chart = { title: string; unit: string; quantity: 'f' | 'v' | 'i' | 'loading' | 'p' | 'q'; labels: string[]; pick: number[]; digits: number }

/**
 * What is known of the selected line, substation or load: what the graph says of it (in service, its
 * breakers), its live values and their last 30 s as the simulation measures them, and what can be
 * done to it (operate it, disturb it). The values reach the panel through the live buffer, never
 * through React state, as on the rest of the page.
 */
export function DetailPanel({
  target,
  layout,
  state,
  pending,
  editable,
  live,
  disturb,
  onOperate,
  onBreaker,
  onClose,
}: {
  target: MenuTarget
  layout: CimLayout
  state: CimGraphState | null
  pending: ReadonlyMap<string, unknown>
  editable: boolean
  live: Live
  disturb: Disturb
  onOperate: (branch: CimLayout['branches'][number], isOut: boolean) => void
  onBreaker: (mrid: string, isOpen: boolean) => void
  onClose: () => void
}) {
  const names = useMemo(() => new Map(layout.substations.map((s) => [s.mrid, s.name])), [layout])
  const stationNames = useMemo(() => live.stations.map((s) => s.name), [live.stations])
  const endLabels = useMemo(() => live.lineEnds.map((e) => `end ${e.end} (${e.station})`), [live.lineEnds])
  const injectionNames = useMemo(() => live.injections.map((i) => i.name), [live.injections])

  const { kind, title, facts, readings, charts } = useMemo(() => {
    const facts: [string, string][] = []
    const readings: Reading[] = []
    const charts: Chart[] = []
    if (target.kind === 'branch') {
      const { branch } = target
      const isOut = state?.out_of_service.includes(branch.mrid) ?? false
      if (branch.from_substation === branch.to_substation) facts.push(['In', names.get(branch.from_substation) ?? '?'])
      else facts.push(['Between', `${names.get(branch.from_substation) ?? '?'} and ${names.get(branch.to_substation) ?? '?'}`])
      facts.push(['In the graph', isOut ? 'out of service' : 'in service'])
      const breaker = branch.breaker ? layout.breakers.find((b) => b.mrid === branch.breaker) : undefined
      facts.push(['Operated by', breaker ? `${breaker.name} (${state?.switches[breaker.mrid] ? 'open' : 'closed'})` : 'its terminal (no breaker of its own)'])
      const ends = live.lineEnds.flatMap((end, i) => (end.line === branch.mrid ? [i] : []))
      for (const i of ends) {
        const end = live.lineEnds[i]
        readings.push({
          label: `Current, ${endLabels[i]}`,
          read: (b) => {
            const loading = newest(b.loading[i])
            return `${fixed(newest(b.i[i]), 0, 'A')}${loading === null ? '' : ` · ${(loading * 100).toFixed(0)} % of ${end.limit_a} A`}`
          },
        })
      }
      if (ends.length) charts.push({ title: 'Current', unit: 'A', quantity: 'i', labels: endLabels, pick: ends, digits: 0 })
      if (ends.some((i) => live.lineEnds[i].limit_a !== null)) {
        charts.push({ title: 'Loading', unit: '× limit', quantity: 'loading', labels: endLabels, pick: ends, digits: 3 })
      }
      return { kind: branch.kind, title: branch.name, facts, readings, charts }
    }
    if (target.kind === 'substation') {
      const { substation } = target
      const breakers = layout.breakers.filter((b) => b.substation === substation.mrid)
      facts.push(['Breakers', breakers.length ? breakers.map((b) => `${b.name} (${state?.switches[b.mrid] ? 'open' : 'closed'})`).join(', ') : 'none'])
      facts.push(['Nodes', substation.nodes.map((n) => `${n.name}${n.nominal_kv === null ? '' : ` ${n.nominal_kv} kV`}`).join(', ') || 'none'])
      const stations = live.stations.flatMap((s, i) => (s.substation === substation.mrid ? [i] : []))
      for (const i of stations) {
        readings.push({ label: stationNames[i], read: (b) => `${fixed(newest(b.v[i]), 4, 'p.u.')} · ${fixed(newest(b.f[i]), 4, 'Hz')}` })
      }
      const here = new Set(stations.map((i) => stationNames[i]))
      live.injections.forEach((injection, i) => {
        if (!here.has(injection.station)) return
        readings.push({ label: `${injection.name} (${injection.kind})`, read: (b) => `${fixed(newest(b.p[i]), 1, 'MW')} · ${fixed(newest(b.q[i]), 1, 'Mvar')}` })
      })
      if (stations.length) {
        charts.push({ title: 'Frequency', unit: 'Hz', quantity: 'f', labels: stationNames, pick: stations, digits: 4 })
        charts.push({ title: 'Voltage', unit: 'p.u.', quantity: 'v', labels: stationNames, pick: stations, digits: 4 })
      }
      return { kind: 'substation', title: substation.name, facts, readings, charts }
    }
    const { load } = target
    facts.push(['In', names.get(load.substation) ?? load.substation])
    facts.push(['In the graph', `${fixed(load.p_mw, 1, 'MW')} · ${fixed(load.q_mvar, 1, 'Mvar')}`])
    const i = live.injections.findIndex((injection) => injection.mrid === load.mrid)
    if (i >= 0) {
      readings.push({ label: 'Drawing now', read: (b) => `${fixed(newest(b.p[i]), 1, 'MW')} · ${fixed(newest(b.q[i]), 1, 'Mvar')}` })
      charts.push({ title: 'Active power', unit: 'MW', quantity: 'p', labels: injectionNames, pick: [i], digits: 1 })
      charts.push({ title: 'Reactive power', unit: 'Mvar', quantity: 'q', labels: injectionNames, pick: [i], digits: 1 })
    }
    return { kind: 'load', title: load.name, facts, readings, charts }
  }, [target, state, names, layout.breakers, live.lineEnds, live.stations, live.injections, endLabels, stationNames, injectionNames])

  const { items } = disturbancesOf(target, disturb)
  const branch = target.kind === 'branch' ? target.branch : null
  const isOut = branch ? (state?.out_of_service.includes(branch.mrid) ?? false) : false
  const switching = branch ? pending.has(branch.mrid) || (!!branch.breaker && pending.has(branch.breaker)) : false
  const breakers = target.kind === 'substation' ? layout.breakers.filter((b) => b.substation === target.substation.mrid) : []

  return (
    <aside className="space-y-3 rounded-md border p-3" aria-label={`${title}, ${kind}`} data-testid="detail-panel">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-medium">{title}</div>
          <div className="text-muted-foreground text-xs">{kind}</div>
        </div>
        <Button size="icon" variant="ghost" className="size-7" aria-label="Close" onClick={onClose}>
          <XIcon className="size-4" />
        </Button>
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        {facts.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>

      <section className="space-y-1">
        <h3 className="text-xs font-medium">Live, as the simulation measures it</h3>
        <LiveValues readings={readings} buffer={live.buffer} subscribe={live.subscribe} />
      </section>

      {charts.map((chart) => (
        <LiveChart
          key={`${chart.quantity}-${chart.pick.join(',')}`}
          title={chart.title}
          unit={chart.unit}
          quantity={chart.quantity}
          labels={chart.labels}
          pick={chart.pick}
          buffer={live.buffer}
          subscribe={live.subscribe}
          digits={chart.digits}
          height={140}
        />
      ))}

      <section className="space-y-1">
        <h3 className="text-xs font-medium">Operate</h3>
        {branch && (
          <Button size="sm" variant="outline" disabled={!editable || switching} onClick={() => onOperate(branch, isOut)}>
            {switching ? 'Switching…' : isOut ? 'Bring back into service' : 'Take out of service'}
          </Button>
        )}
        {breakers.map((b) => {
          const open = state?.switches[b.mrid] ?? false
          return (
            <Button key={b.mrid} size="sm" variant="outline" className="mr-1" disabled={!editable || pending.has(b.mrid)} onClick={() => onBreaker(b.mrid, open)}>
              {open ? 'Close' : 'Open'} {b.name}
            </Button>
          )
        })}
        {!branch && breakers.length === 0 && <p className="text-muted-foreground text-xs">Nothing to operate here.</p>}
      </section>

      <section className="space-y-1">
        <h3 className="text-xs font-medium">Disturb the simulation</h3>
        <div className="flex flex-wrap gap-1">
          {items.map((item) => (
            <Button key={item.label} size="sm" variant="secondary" title={item.hint} disabled={!editable} onClick={item.run}>
              {item.label}
            </Button>
          ))}
          {items.length === 0 && <p className="text-muted-foreground text-xs">Nothing to disturb here.</p>}
        </div>
      </section>
    </aside>
  )
}
