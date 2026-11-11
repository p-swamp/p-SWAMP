import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import './gridMap.css'
import { loadingColor } from './colors'
import type { CimGraphState, CimLayout } from './useCimGraphSocket'
import { scadaValue } from './scada'
import type { LiveBuffer, LiveLineEnd, LiveScadaPoint, LiveStation } from './useLiveFeed'

const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
const OK = '#16a34a'
const OUT = '#ef4444'
const PENDING = '#f59e0b'
/** How often the live colours are refreshed: a map need not follow 50 frames a second. */
const LIVE_MS = 250

type Branch = CimLayout['branches'][number]

/** What a right-click (or a long press) is on: what a disturbance can be aimed at. */
export type MenuTarget =
  | { kind: 'branch'; branch: Branch }
  | { kind: 'substation'; substation: CimLayout['substations'][number] }
  | { kind: 'load'; load: CimLayout['loads'][number] }
  | { kind: 'generator'; generator: NonNullable<CimLayout['generators']>[number] }

/** A right-click on the map: on what, and where in the map's box (pixels). */
export type MenuRequest = { target: MenuTarget; x: number; y: number }

/** A frequency deviation as a colour: blue below 50 Hz, red above, grey on it; full at ±0.2 Hz. */
function frequencyColor(f: number | null | undefined): string {
  if (f === null || f === undefined) return '#94a3b8'
  const x = Math.max(-1, Math.min(1, (f - 50) / 0.2))
  const fade = (a: number, b: number) => Math.round(a + (b - a) * Math.abs(x))
  return x < 0 ? `rgb(${fade(148, 37)},${fade(163, 99)},${fade(184, 235)})` : `rgb(${fade(148, 220)},${fade(163, 38)},${fade(184, 38)})`
}

/** A line's weight: thicker when it is the selected one. */
/** A transformer's symbol: two overlapping windings. Its colour is the element's (``.cim-transformer``). */
const TRANSFORMER_ICON =
  '<svg width="20" height="12" viewBox="0 0 20 12" aria-hidden="true"><circle cx="6" cy="6" r="5" /><circle cx="14" cy="6" r="5" /></svg>'

/** A generator's symbol: a circle with a sine in it. Its colour is the element's (``.cim-generator``). */
const GENERATOR_ICON =
  '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="6" /><path d="M3.5 7 q1.75 -3.5 3.5 0 t3.5 0" /></svg>'

/** The point halfway along ``points``: where a branch's symbol goes. */
function middle(points: L.LatLng[]): L.LatLng {
  const i = Math.floor((points.length - 1) / 2)
  const [a, b] = [points[i], points[Math.min(i + 1, points.length - 1)]]
  return points.length % 2 === 1 ? points[i] : L.latLng((a.lat + b.lat) / 2, (a.lng + b.lng) / 2)
}

const thicker = (mrid: string, selected: string | null, weight: number) => (mrid === selected ? weight + 3 : weight)

function title(element: Element | undefined, text: string) {
  if (!element) return
  let node: Element | null = element.querySelector('title')
  if (!node) {
    node = document.createElementNS('http://www.w3.org/2000/svg', 'title')
    element.appendChild(node)
  }
  node.textContent = text
}

type Layers = {
  map: L.Map
  lines: Map<string, { line: L.Polyline; hit: L.Polyline; branch: Branch }>
  /** Each transformer's symbol: at the middle of its segment, or beside its substation. */
  transformers: Map<string, { marker: L.Marker; branch: Branch }>
  breakers: Map<string, L.Marker>
  substations: Map<string, L.CircleMarker>
  loads: Map<string, L.Marker>
  generators: Map<string, L.Marker>
}

/**
 * The grid on its geographic layout (the graph's GL profile), on OpenStreetMap: substations, lines,
 * breakers, generators (above their substation) and loads (below). A line in service is coloured by its
 * loading, when it has a limit. A click on a breaker operates it; a click on a line, a substation, a
 * generator or a load selects it (`onSelect`: the page
 * shows it in a panel); a right-click (a long press) on one asks for its disturbances (`onMenu`).
 * Leaflet is driven directly (react-leaflet's licence does not pass dependency review): the layers
 * are built once per layout and restyled in place, from the graph's state (out of service, open,
 * switching) and, four times a second, from the live feed (each substation coloured by its frequency
 * deviation, and its voltage and frequency on hover; a breaker whose position in the latest SCADA scan
 * is not the graph's marked as such).
 */
export function GridMap({
  layout,
  state,
  pending,
  editable,
  onBreaker,
  onSelect,
  selected,
  stations,
  lineEnds,
  scada = [],
  buffer,
  subscribe,
  highlight,
  onPick,
  onMenu,
}: {
  layout: CimLayout
  state: CimGraphState | null
  pending: ReadonlyMap<string, unknown>
  editable: boolean
  onBreaker: (mrid: string, isOpen: boolean) => void
  onSelect: (target: MenuTarget | null) => void
  selected: string | null
  stations: LiveStation[]
  lineEnds: LiveLineEnd[]
  /** The grid's SCADA points (``buffer.scan`` lists their values): the switches' positions are checked against the graph. */
  scada?: LiveScadaPoint[]
  buffer: React.RefObject<LiveBuffer>
  subscribe: (listener: () => void) => () => void
  highlight: string | null
  onPick: (substation: string | null) => void
  onMenu: (request: MenuRequest | null) => void
}) {
  const container = useRef<HTMLDivElement | null>(null)
  const layers = useRef<Layers | null>(null)
  /** The lines the graph's state colours (out of service, switching): loading does not recolour them. */
  const stateColoured = useRef(new Set<string>())
  // The latest props, for the handlers the layers were built with.
  const props = useRef({ state, editable, onBreaker, onSelect, onPick, onMenu })
  useEffect(() => {
    props.current = { state, editable, onBreaker, onSelect, onPick, onMenu }
  })
  /** The selected element's mRID, for the live paint: it is drawn thicker. */
  const chosen = useRef(selected)
  useEffect(() => {
    chosen.current = selected
  }, [selected])

  // Build the map and its layers, once per layout.
  useEffect(() => {
    const node = container.current
    if (!node || layout.substations.length === 0) return
    const map = L.map(node, { preferCanvas: false, zoomSnap: 0.25 })
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: 18 }).addTo(map)
    map.on('click', () => {
      props.current.onPick(null)
      props.current.onSelect(null)
      props.current.onMenu(null)
    })
    map.on('contextmenu movestart zoomstart', () => props.current.onMenu(null))
    /** A right-click on a layer: its menu, at the click, and not the map's own. */
    const menu = (target: MenuTarget) => (event: L.LeafletMouseEvent) => {
      L.DomEvent.stopPropagation(event)
      L.DomEvent.preventDefault(event.originalEvent)
      if (props.current.editable) props.current.onMenu({ target, x: event.containerPoint.x, y: event.containerPoint.y })
    }
    const at = new Map(layout.substations.map((s) => [s.mrid, L.latLng(s.position.lat, s.position.lon)]))
    // The view first: Leaflet renders a layer only once its map has one, so until then a layer has no
    // element to label (getElement() is undefined) and the labels below would be silently skipped.
    map.fitBounds(L.latLngBounds([...at.values()]), { padding: [24, 24] })
    const built: Layers = {
      map,
      lines: new Map(),
      breakers: new Map(),
      substations: new Map(),
      loads: new Map(),
      generators: new Map(),
      transformers: new Map(),
    }

    const inside = new Map<string, number>() // substation -> transformers drawn beside it so far
    for (const branch of layout.branches) {
      const within = branch.from_substation === branch.to_substation
      const points =
        branch.path.length >= 2
          ? branch.path.map((p) => L.latLng(p.lat, p.lon))
          : [at.get(branch.from_substation), at.get(branch.to_substation)].filter((p): p is L.LatLng => !!p)
      if (branch.kind === 'transformer') {
        // Its symbol: at the middle of its segment, or above its substation when both ends are in it.
        const i = within ? (inside.get(branch.from_substation) ?? 0) : 0
        if (within) inside.set(branch.from_substation, i + 1)
        const where = within ? at.get(branch.from_substation) : points.length >= 2 ? middle(points) : undefined
        if (where) {
          const marker = L.marker(where, {
            icon: L.divIcon({ className: 'cim-transformer', html: TRANSFORMER_ICON, iconSize: [20, 12], iconAnchor: within ? [10 - 24 * i, 30] : [10, 6] }),
            keyboard: false,
            zIndexOffset: 500,
          })
            .on('click', (event) => {
              L.DomEvent.stopPropagation(event)
              props.current.onSelect({ kind: 'branch', branch })
            })
            .on('contextmenu', menu({ kind: 'branch', branch }))
            .addTo(map)
          const element = marker.getElement()
          element?.setAttribute('data-testid', `transformer-${branch.name}`)
          element?.setAttribute('role', 'button')
          built.transformers.set(branch.mrid, { marker, branch })
        }
      }
      if (within || points.length < 2) continue // a transformer inside its substation has no segment
      const line = L.polyline(points, { weight: 3, color: OK, interactive: false }).addTo(map)
      // A wide, invisible twin takes the click: a 3 px line is a small target.
      const hit = L.polyline(points, { weight: 14, opacity: 0, bubblingMouseEvents: false })
        .on('click', () => props.current.onSelect({ kind: 'branch', branch }))
        .on('contextmenu', menu({ kind: 'branch', branch }))
        .addTo(map)
      hit.getElement()?.setAttribute('data-testid', `line-${branch.name}`)
      built.lines.set(branch.mrid, { line, hit, branch })
    }

    for (const s of layout.substations) {
      const marker = L.circleMarker(at.get(s.mrid)!, { radius: 7, weight: 2, color: '#1e293b', fillOpacity: 0.95, fillColor: '#94a3b8' })
        .on('click', (event) => {
          L.DomEvent.stopPropagation(event)
          props.current.onPick(s.mrid)
          props.current.onSelect({ kind: 'substation', substation: s })
        })
        .on('contextmenu', menu({ kind: 'substation', substation: s }))
        .bindTooltip(s.name)
        .addTo(map)
      marker.getElement()?.setAttribute('data-testid', `substation-${s.name}`)
      built.substations.set(s.mrid, marker)
    }

    // Breakers in a small ring around their substation, offset in pixels so they stay apart at any zoom.
    const per = new Map<string, number>()
    layout.breakers.forEach((b) => per.set(b.substation, (per.get(b.substation) ?? 0) + 1))
    const seen = new Map<string, number>()
    for (const b of layout.breakers) {
      const centre = at.get(b.substation)
      if (!centre) continue
      const i = seen.get(b.substation) ?? 0
      seen.set(b.substation, i + 1)
      const count = per.get(b.substation) ?? 1
      const radius = Math.max(16, (count * 12) / (2 * Math.PI))
      const angle = (2 * Math.PI * i) / count
      const [dx, dy] = [radius * Math.cos(angle), radius * Math.sin(angle)]
      const marker = L.marker(centre, {
        icon: L.divIcon({ className: 'cim-breaker', iconSize: [10, 10], iconAnchor: [5 - dx, 5 - dy] }),
        keyboard: false,
      })
        .on('click', (event) => {
          L.DomEvent.stopPropagation(event)
          const open = props.current.state?.switches[b.mrid] ?? false
          if (props.current.editable) props.current.onBreaker(b.mrid, open)
        })
        .addTo(map)
      const element = marker.getElement()
      element?.setAttribute('data-testid', `breaker-${b.name}`)
      element?.setAttribute('role', 'button')
      built.breakers.set(b.mrid, marker)
    }

    // Loads in a row below their substation, offset in pixels like the breakers.
    const loadsSeen = new Map<string, number>()
    for (const load of layout.loads) {
      const centre = at.get(load.substation)
      if (!centre) continue
      const i = loadsSeen.get(load.substation) ?? 0
      loadsSeen.set(load.substation, i + 1)
      const marker = L.marker(centre, {
        icon: L.divIcon({ className: 'cim-load', iconSize: [10, 10], iconAnchor: [5 - 12 * i, -18] }),
        keyboard: false,
      })
        .on('click', (event) => {
          L.DomEvent.stopPropagation(event)
          props.current.onSelect({ kind: 'load', load })
        })
        .on('contextmenu', menu({ kind: 'load', load }))
        .addTo(map)
      const element = marker.getElement()
      element?.setAttribute('data-testid', `load-${load.name}`)
      if (element) element.title = `${load.name} (load${load.p_mw === null ? '' : `, ${load.p_mw} MW`}): click for its values, right-click for a load step`
      built.loads.set(load.mrid, marker)
    }

    // Generators in a row above their substation, over the transformers drawn inside it. No menu:
    // the simulation has no disturbance of a machine.
    const generatorsSeen = new Map<string, number>()
    for (const generator of layout.generators ?? []) {
      const centre = at.get(generator.substation)
      if (!centre) continue
      const i = generatorsSeen.get(generator.substation) ?? 0
      generatorsSeen.set(generator.substation, i + 1)
      const marker = L.marker(centre, {
        icon: L.divIcon({ className: 'cim-generator', html: GENERATOR_ICON, iconSize: [14, 14], iconAnchor: [7 - 16 * i, 46] }),
        keyboard: false,
      })
        .on('click', (event) => {
          L.DomEvent.stopPropagation(event)
          props.current.onSelect({ kind: 'generator', generator })
        })
        .on('contextmenu', (event) => {
          L.DomEvent.stopPropagation(event)
          L.DomEvent.preventDefault(event.originalEvent)
        })
        .addTo(map)
      const element = marker.getElement()
      element?.setAttribute('data-testid', `generator-${generator.name}`)
      if (element) {
        element.dataset.substation = layout.substations.find((s) => s.mrid === generator.substation)?.name ?? ''
        const mw = generator.p_mw === null ? '' : `, ${generator.p_mw} MW`
        element.title = `${generator.name} (generator${mw}): click for its values`
      }
      built.generators.set(generator.mrid, marker)
    }

    layers.current = built
    return () => {
      map.remove()
      layers.current = null
    }
  }, [layout])

  // The graph's state: what is out of service, open, or switching.
  useEffect(() => {
    const built = layers.current
    if (!built) return
    const out = new Set(state?.out_of_service ?? [])
    stateColoured.current = new Set()
    const names = new Map(layout.substations.map((s) => [s.mrid, s.name]))
    const breakerNames = new Map(layout.breakers.map((b) => [b.mrid, b.name]))
    for (const [mrid, { line, hit, branch }] of built.lines) {
      const isOut = out.has(mrid)
      const switching = pending.has(mrid) || (!!branch.breaker && pending.has(branch.breaker))
      if (isOut || switching) stateColoured.current.add(mrid)
      line.setStyle({
        color: switching ? PENDING : isOut ? OUT : OK,
        dashArray: isOut ? '6 5' : undefined,
        weight: thicker(mrid, selected, isOut || switching ? 3.5 : 3),
      })
      const element = hit.getElement()
      element?.setAttribute('data-selected', String(mrid === selected))
      element?.setAttribute('data-out', String(isOut))
      element?.setAttribute('data-pending', String(switching))
      element?.classList.add('cursor-pointer')
      const via = branch.breaker ? `operated by ${breakerNames.get(branch.breaker) ?? branch.breaker}` : 'no breaker of its own'
      title(
        element,
        `${branch.name} (${branch.kind}, ${names.get(branch.from_substation) ?? '?'} to ${names.get(branch.to_substation) ?? '?'}): ` +
          `${isOut ? 'out of service' : 'in service'}, ${via}${switching ? ' · switching…' : ''}`,
      )
    }
    for (const b of layout.breakers) {
      const element = built.breakers.get(b.mrid)?.getElement()
      if (!element) continue
      const isOpen = state?.switches[b.mrid] ?? false
      const switching = pending.has(b.mrid)
      element.dataset.open = String(isOpen)
      element.dataset.pending = String(switching)
      // toggled, not set: Leaflet keeps classes of its own on the marker
      element.classList.toggle('cim-breaker-pending', switching)
      element.classList.toggle('cim-breaker-open', !switching && isOpen)
      element.classList.toggle('cim-breaker-closed', !switching && !isOpen)
      element.title = `${b.name} (breaker, ${names.get(b.substation) ?? b.substation}): ${isOpen ? 'open' : 'closed'}${switching ? ' · switching…' : ''}`
    }
    for (const [mrid, { marker, branch }] of built.transformers) {
      const element = marker.getElement()
      if (!element) continue
      const isOut = out.has(mrid)
      const switching = pending.has(mrid) || (!!branch.breaker && pending.has(branch.breaker))
      element.dataset.out = String(isOut)
      element.dataset.pending = String(switching)
      element.dataset.selected = String(mrid === selected)
      element.classList.toggle('cim-transformer-out', !switching && isOut)
      element.classList.toggle('cim-transformer-pending', switching)
      element.classList.toggle('cim-selected', mrid === selected)
      const between =
        branch.from_substation === branch.to_substation
          ? `in ${names.get(branch.from_substation) ?? '?'}`
          : `${names.get(branch.from_substation) ?? '?'} to ${names.get(branch.to_substation) ?? '?'}`
      element.title = `${branch.name} (transformer, ${between}): ${isOut ? 'out of service' : 'in service'}${switching ? ' · switching…' : ''}`
    }
    for (const [mrid, marker] of [...built.loads, ...built.generators]) {
      const element = marker.getElement()
      element?.setAttribute('data-selected', String(mrid === selected))
      element?.classList.toggle('cim-selected', mrid === selected)
    }
  }, [layout, state, pending, editable, selected])

  // The highlighted substation stands out.
  useEffect(() => {
    for (const [mrid, marker] of layers.current?.substations ?? []) {
      marker.setStyle(mrid === highlight ? { radius: 11, weight: 4, color: '#0f172a' } : { radius: 7, weight: 2, color: '#1e293b' })
    }
  }, [highlight, layout])

  // Live colours, four times a second: each substation by the frequency of its highest-voltage station.
  useEffect(() => {
    let last = 0
    const paint = () => {
      const now = performance.now()
      if (now - last < LIVE_MS) return
      last = now
      const built = layers.current
      const buf = buffer.current
      if (!built || stations.length === 0) return
      const best = new Map<string, number>() // substation -> station index (highest kV)
      stations.forEach((station, i) => {
        if (!station.substation) return
        const j = best.get(station.substation)
        if (j === undefined || (station.kv ?? 0) > (stations[j].kv ?? 0)) best.set(station.substation, i)
      })
      for (const [mrid, marker] of built.substations) {
        const i = best.get(mrid)
        const f = i === undefined ? null : buf.f[i]?.[buf.f[i].length - 1]
        const v = i === undefined ? null : buf.v[i]?.[buf.v[i].length - 1]
        marker.setStyle({ fillColor: frequencyColor(f) })
        const name = layout.substations.find((s) => s.mrid === mrid)?.name ?? mrid
        marker.setTooltipContent(
          f === null || f === undefined ? name : `${name}: ${f.toFixed(4)} Hz · ${v === null || v === undefined ? '—' : v.toFixed(3)} p.u.`,
        )
      }
      // Each line by the more loaded of its ends, unless the graph's state colours it.
      const loading = new Map<string, number>()
      lineEnds.forEach((end, i) => {
        const value = buf.loading[i]?.[buf.loading[i].length - 1]
        if (value !== null && value !== undefined) loading.set(end.line, Math.max(value, loading.get(end.line) ?? 0))
      })
      for (const [mrid, { line, hit }] of built.lines) {
        const value = loading.get(mrid)
        hit.getElement()?.setAttribute('data-loading', value === undefined ? '' : value.toFixed(3))
        if (stateColoured.current.has(mrid)) continue
        const weight = thicker(mrid, chosen.current, value !== undefined && value >= 1 ? 5 : 3)
        line.setStyle({ color: value === undefined ? OK : loadingColor(value), weight })
      }
      // Each breaker whose position, as SCADA last scanned it, is not the graph's.
      scada.forEach((point, i) => {
        if (point.quantity !== 'Pos') return
        const element = built.breakers.get(point.equipment)?.getElement()
        if (!element) return
        const value = scadaValue(buf, i)
        const graphOpen = props.current.state?.switches[point.equipment]
        const scadaOpen = value === null ? undefined : value === 0
        const mismatch = scadaOpen !== undefined && graphOpen !== undefined && scadaOpen !== graphOpen
        element.dataset.scada = scadaOpen === undefined ? '' : scadaOpen ? 'open' : 'closed'
        element.dataset.mismatch = String(mismatch)
        element.classList.toggle('cim-breaker-mismatch', mismatch)
      })
    }
    return subscribe(paint)
  }, [buffer, layout, lineEnds, scada, stations, subscribe])

  return <div ref={container} className="h-[60vh] w-full rounded-md border" role="region" aria-label="The grid on its geographic layout" />
}
