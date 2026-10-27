import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import './gridMap.css'
import type { CimGraphState, CimLayout } from './useCimGraphSocket'
import type { LiveBuffer, LiveStation } from './useLiveFeed'

const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
const OK = '#16a34a'
const OUT = '#ef4444'
const PENDING = '#f59e0b'
/** How often the live colours are refreshed: a map need not follow 50 frames a second. */
const LIVE_MS = 250

type Branch = CimLayout['branches'][number]

/** A frequency deviation as a colour: blue below 50 Hz, red above, grey on it; full at ±0.2 Hz. */
function frequencyColor(f: number | null | undefined): string {
  if (f === null || f === undefined) return '#94a3b8'
  const x = Math.max(-1, Math.min(1, (f - 50) / 0.2))
  const fade = (a: number, b: number) => Math.round(a + (b - a) * Math.abs(x))
  return x < 0 ? `rgb(${fade(148, 37)},${fade(163, 99)},${fade(184, 235)})` : `rgb(${fade(148, 220)},${fade(163, 38)},${fade(184, 38)})`
}

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
  breakers: Map<string, L.Marker>
  substations: Map<string, L.CircleMarker>
}

/**
 * The grid on its geographic layout (the graph's GL profile), on OpenStreetMap: substations, lines and
 * breakers. Leaflet is driven directly (react-leaflet's licence does not pass dependency review): the
 * layers are built once per layout and restyled in place, from the graph's state (out of service,
 * open, switching) and, four times a second, from the live feed (each substation coloured by its
 * frequency deviation, and its voltage and frequency on hover).
 */
export function GridMap({
  layout,
  state,
  pending,
  editable,
  onBreaker,
  onLine,
  stations,
  buffer,
  subscribe,
  highlight,
  onPick,
}: {
  layout: CimLayout
  state: CimGraphState | null
  pending: ReadonlyMap<string, unknown>
  editable: boolean
  onBreaker: (mrid: string, isOpen: boolean) => void
  onLine: (branch: Branch, isOut: boolean) => void
  stations: LiveStation[]
  buffer: React.RefObject<LiveBuffer>
  subscribe: (listener: () => void) => () => void
  highlight: string | null
  onPick: (substation: string | null) => void
}) {
  const container = useRef<HTMLDivElement | null>(null)
  const layers = useRef<Layers | null>(null)
  // The latest props, for the handlers the layers were built with.
  const props = useRef({ state, editable, onBreaker, onLine, onPick })
  useEffect(() => {
    props.current = { state, editable, onBreaker, onLine, onPick }
  })

  // Build the map and its layers, once per layout.
  useEffect(() => {
    const node = container.current
    if (!node || layout.substations.length === 0) return
    const map = L.map(node, { preferCanvas: false, zoomSnap: 0.25 })
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: 18 }).addTo(map)
    map.on('click', () => props.current.onPick(null))
    const at = new Map(layout.substations.map((s) => [s.mrid, L.latLng(s.position.lat, s.position.lon)]))
    const built: Layers = { map, lines: new Map(), breakers: new Map(), substations: new Map() }

    for (const branch of layout.branches) {
      const points =
        branch.path.length >= 2
          ? branch.path.map((p) => L.latLng(p.lat, p.lon))
          : [at.get(branch.from_substation), at.get(branch.to_substation)].filter((p): p is L.LatLng => !!p)
      if (points.length < 2) continue
      const line = L.polyline(points, { weight: 3, color: OK, interactive: false }).addTo(map)
      // A wide, invisible twin takes the click: a 3 px line is a small target.
      const hit = L.polyline(points, { weight: 14, opacity: 0, bubblingMouseEvents: false })
        .on('click', () => {
          const out = new Set(props.current.state?.out_of_service ?? [])
          if (props.current.editable) props.current.onLine(branch, out.has(branch.mrid))
        })
        .addTo(map)
      hit.getElement()?.setAttribute('data-testid', `line-${branch.name}`)
      built.lines.set(branch.mrid, { line, hit, branch })
    }

    for (const s of layout.substations) {
      const marker = L.circleMarker(at.get(s.mrid)!, { radius: 7, weight: 2, color: '#1e293b', fillOpacity: 0.95, fillColor: '#94a3b8' })
        .on('click', (event) => {
          L.DomEvent.stopPropagation(event)
          props.current.onPick(s.mrid)
        })
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

    map.fitBounds(L.latLngBounds([...at.values()]), { padding: [24, 24] })
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
    const names = new Map(layout.substations.map((s) => [s.mrid, s.name]))
    const breakerNames = new Map(layout.breakers.map((b) => [b.mrid, b.name]))
    for (const [mrid, { line, hit, branch }] of built.lines) {
      const isOut = out.has(mrid)
      const switching = pending.has(mrid) || (!!branch.breaker && pending.has(branch.breaker))
      line.setStyle({ color: switching ? PENDING : isOut ? OUT : OK, dashArray: isOut ? '6 5' : undefined, weight: isOut || switching ? 3.5 : 3 })
      const element = hit.getElement()
      element?.setAttribute('data-out', String(isOut))
      element?.setAttribute('data-pending', String(switching))
      element?.classList.toggle('cursor-pointer', editable)
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
  }, [layout, state, pending, editable])

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
    }
    return subscribe(paint)
  }, [buffer, layout, stations, subscribe])

  return <div ref={container} className="h-[60vh] w-full rounded-md border" role="region" aria-label="The grid on its geographic layout" />
}
