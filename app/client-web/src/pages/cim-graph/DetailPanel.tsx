import { useEffect, useMemo, useRef } from 'react'
import { XIcon } from 'lucide-react'

import { disturbancesOf } from './disturbances'
import type { Disturb } from './disturbances'
import type { MenuTarget } from './GridMap'
import { LiveChart } from './LiveChart'
import { intoEquipment, pointsOn, scadaValue, scanTime } from './scada'
import type { CimGraphState, CimLayout } from './useCimGraphSocket'
import type { LiveBuffer, LiveInjection, LiveLineEnd, LiveScadaPoint, LiveStation } from './useLiveFeed'
import { Button } from '@/components/ui/button'

/** How often the live values are rewritten: a reader need not follow 50 frames a second. */
const EVERY_MS = 250

type Live = {
  stations: LiveStation[]
  lineEnds: LiveLineEnd[]
  injections: LiveInjection[]
  scada: LiveScadaPoint[]
  buffer: React.RefObject<LiveBuffer>
  subscribe: (listener: () => void) => () => void
}

/** One live value: a label, and how to read its text off the buffer; a group's heading (its total), or
 *  a member of the group above. */
type Reading = { label: string; read: (buffer: LiveBuffer) => string; heading?: boolean; indent?: boolean }

const newest = (series: (number | null)[] | undefined) => series?.[series.length - 1] ?? null
const fixed = (x: number | null, digits: number, unit: string) => (x === null ? '—' : `${x.toFixed(digits)} ${unit}`)

type Injection = 'generator' | 'load'

/** A machine's or a load's power as one reads it: a machine's as it generates (out of it), a load's as
 *  it draws (into it). The simulation and SCADA both sign it into the equipment, as CGMES does. */
const asRead = (kind: Injection, into: number | null) => (into === null ? null : (kind === 'generator' ? -into : into) + 0)

/** P and Q, as read, summed over what has a value; null when nothing has. */
function sum(values: (number | null)[]): number | null {
  const known = values.filter((x): x is number => x !== null)
  return known.length ? known.reduce((a, b) => a + b, 0) : null
}

const power = (p: number | null, q: number | null) => `${fixed(p, 1, 'MW')} · ${fixed(q, 1, 'Mvar')}`

/** What the latest SCADA scan says of `points`, one reading per thing measured (`label` names it): a
 *  branch end's P and Q (and I), a machine's or a load's P and Q, a voltage level's V, a switch's
 *  position. `asPower` turns a P or a Q as SCADA has it into how it is read. */
function scadaReadings(
  points: [LiveScadaPoint, number][],
  label: (point: LiveScadaPoint) => string,
  asPower: (point: LiveScadaPoint, value: number) => number | null = (_, value) => value,
): Reading[] {
  const groups = new Map<string, [LiveScadaPoint, number][]>()
  for (const entry of points) {
    const key = label(entry[0])
    groups.set(key, [...(groups.get(key) ?? []), entry])
  }
  return [...groups].map(([key, group]) => ({
    label: key,
    read: (b: LiveBuffer) =>
      group
        .map(([point, i]) => {
          const value = scadaValue(b, i)
          if (point.quantity === 'Pos') return value === null ? '—' : value === 1 ? 'closed' : 'open'
          const shown = value !== null && (point.quantity === 'P' || point.quantity === 'Q') ? asPower(point, value) : value
          return fixed(shown, point.quantity === 'I' ? 0 : 1, point.unit)
        })
        .join(' · '),
  }))
}

/** The SCADA of a substation's generators or loads: a heading with their total, then each, its P and Q
 *  as read (a machine's generated, a load's drawn). Nothing when there is none. */
function scadaInjections(kind: Injection, points: [LiveScadaPoint, number][]): Reading[] {
  if (points.length === 0) return []
  const asPower = (point: LiveScadaPoint, value: number) => asRead(kind, intoEquipment(point, value))
  const total = (b: LiveBuffer, quantity: 'P' | 'Q') =>
    sum(
      points
        .filter(([point]) => point.quantity === quantity)
        .map(([point, i]) => {
          const value = scadaValue(b, i)
          return value === null ? null : asPower(point, value)
        }),
    )
  const members = scadaReadings(points, (point) => point.name ?? point.equipment, asPower)
  return [
    { label: kind === 'generator' ? 'Generation' : 'Load', heading: true, read: (b) => power(total(b, 'P'), total(b, 'Q')) },
    ...members.map((reading) => ({ ...reading, indent: true })),
  ]
}

/** The scan's own reading: when it was made. */
const SCANNED: Reading = {
  label: 'Scanned at',
  read: (b) => {
    const at = scanTime(b)
    const sim = b.scan?.sim_time
    return at === null ? 'not yet' : `${at}${sim === null || sim === undefined ? '' : ` (t = ${sim.toFixed(1)} s)`}`
  },
}

/** The order a thing's values are read in: P, Q, I; a voltage; a position. */
const ORDER = { P: 0, Q: 1, I: 2, V: 3, Pos: 4 } as const
const byQuantity = (a: [LiveScadaPoint, number], b: [LiveScadaPoint, number]) => ORDER[a[0].quantity] - ORDER[b[0].quantity]

/** The live values of the selection, written into the DOM from the buffer, never through a render. */
function LiveValues({
  readings,
  buffer,
  subscribe,
  testId = 'detail-live',
  none = 'The simulation measures nothing here.',
}: {
  readings: Reading[]
  buffer: React.RefObject<LiveBuffer>
  subscribe: Live['subscribe']
  testId?: string
  none?: string
}) {
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
  if (readings.length === 0) return <p className="text-muted-foreground text-xs">{none}</p>
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs" data-testid={testId}>
      {readings.map((reading, i) => (
        <div key={`${reading.heading ? 'h' : 'r'}-${reading.label}`} className="contents">
          <dt className={reading.heading ? 'pt-1 font-medium' : reading.indent ? 'text-muted-foreground pl-3' : 'text-muted-foreground'}>
            {reading.label}
          </dt>
          <dd
            className={reading.heading ? 'pt-1 font-medium tabular-nums' : 'tabular-nums'}
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
 * What is known of the selected line, substation, generator or load: what the graph says of it (in
 * service, its breakers), its live values and their last 30 s as the simulation measures them (a
 * substation's generation and load apart, each with its total; a machine's power as it generates), and what can be
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

  const { kind, title, facts, readings, charts, scada } = useMemo(() => {
    const facts: [string, string][] = []
    const readings: Reading[] = []
    const charts: Chart[] = []
    const scada: Reading[] = []
    const on = (test: (point: LiveScadaPoint) => boolean) => pointsOn(live.scada, test).sort(byQuantity)
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
      const atEnds = on((p) => p.equipment === branch.mrid).sort((a, b) => (a[0].end ?? 0) - (b[0].end ?? 0))
      scada.push(...scadaReadings(atEnds, (p) => `End ${p.end} (${names.get(p.substation ?? '') ?? '?'})`))
      return { kind: branch.kind, title: branch.name, facts, readings, charts, scada }
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
      for (const kind of ['generator', 'load'] as const) {
        const members = live.injections.flatMap((injection, i) => (here.has(injection.station) && injection.kind === kind ? [i] : []))
        if (members.length === 0) continue
        const p = (b: LiveBuffer, i: number) => asRead(kind, newest(b.p[i]))
        const q = (b: LiveBuffer, i: number) => asRead(kind, newest(b.q[i]))
        readings.push({
          label: kind === 'generator' ? 'Generation' : 'Load',
          heading: true,
          read: (b) => power(sum(members.map((i) => p(b, i))), sum(members.map((i) => q(b, i)))),
        })
        for (const i of members) readings.push({ label: live.injections[i].name, indent: true, read: (b) => power(p(b, i), q(b, i)) })
      }
      if (stations.length) {
        charts.push({ title: 'Frequency', unit: 'Hz', quantity: 'f', labels: stationNames, pick: stations, digits: 4 })
        charts.push({ title: 'Voltage', unit: 'p.u.', quantity: 'v', labels: stationNames, pick: stations, digits: 4 })
      }
      const inIt = (kinds: LiveScadaPoint['kind'][]) => on((p) => p.substation === substation.mrid && kinds.includes(p.kind))
      scada.push(...scadaReadings(inIt(['voltage_level']), (p) => `Voltage, ${p.name ?? `${p.kv} kV`}`))
      scada.push(...scadaInjections('generator', inIt(['generator'])))
      scada.push(...scadaInjections('load', inIt(['load'])))
      scada.push(...scadaReadings(inIt(['switch']), (p) => p.name ?? p.equipment))
      return { kind: 'substation', title: substation.name, facts, readings, charts, scada }
    }
    if (target.kind === 'generator') {
      const { generator } = target
      facts.push(['In', names.get(generator.substation) ?? generator.substation])
      facts.push(['In the graph', `${power(generator.p_mw, generator.q_mvar)} generated`])
      if (generator.rated_mva !== null) facts.push(['Rated', fixed(generator.rated_mva, 0, 'MVA')])
      const i = live.injections.findIndex((injection) => injection.mrid === generator.mrid)
      if (i >= 0) {
        readings.push({ label: 'Generating now', read: (b) => power(asRead('generator', newest(b.p[i])), asRead('generator', newest(b.q[i]))) })
        // The charts plot the feed as it is: into the machine, as CGMES signs it.
        charts.push({ title: 'Active power, into the machine', unit: 'MW', quantity: 'p', labels: injectionNames, pick: [i], digits: 1 })
        charts.push({ title: 'Reactive power, into the machine', unit: 'Mvar', quantity: 'q', labels: injectionNames, pick: [i], digits: 1 })
      }
      const asPower = (point: LiveScadaPoint, value: number) => asRead('generator', intoEquipment(point, value))
      scada.push(...scadaReadings(on((p) => p.equipment === generator.mrid), () => 'Generating', asPower))
      return { kind: 'generator', title: generator.name, facts, readings, charts, scada }
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
    scada.push(...scadaReadings(on((p) => p.equipment === load.mrid), () => 'Drawing', (point, value) => asRead('load', intoEquipment(point, value))))
    return { kind: 'load', title: load.name, facts, readings, charts, scada }
  }, [target, state, names, layout.breakers, live.lineEnds, live.stations, live.injections, live.scada, endLabels, stationNames, injectionNames])
  const scadaWithTime = useMemo(() => (scada.length ? [...scada, SCANNED] : scada), [scada])

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
        <h3 className="text-xs font-medium">Live, as the simulation's PMUs measure it</h3>
        <LiveValues readings={readings} buffer={live.buffer} subscribe={live.subscribe} none="No PMU measures here." />
      </section>

      <section className="space-y-1">
        <h3 className="text-xs font-medium">SCADA, as last scanned</h3>
        <LiveValues
          readings={scadaWithTime}
          buffer={live.buffer}
          subscribe={live.subscribe}
          testId="detail-scada"
          none="No SCADA measurement here."
        />
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
