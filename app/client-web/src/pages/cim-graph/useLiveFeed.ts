import { useCallback, useEffect, useRef, useState } from 'react'

import type { Wire } from '@/api/wire'
import { CIM_LIVE_WS_PATH } from '@/lib/servers'
import { useServerSocket } from '@/hooks/useServerSocket'

export type LiveFeed = Wire['LiveFeed']
export type LiveStation = Wire['LiveStation']
export type LiveLineEnd = Wire['LiveLineEnd']
export type LiveInjection = Wire['LiveInjection']
export type LiveScadaPoint = Wire['LiveScadaPoint']
export type LiveScan = Wire['LiveScan']

/** Seconds of history the charts show. */
export const WINDOW_S = 30
/** Seconds the received-samples rate is measured over. */
const RATE_WINDOW_S = 2
/** Seconds between two frames past which they are not joined: frames are stamped one period apart
 *  (20 ms), so a larger step is frames that never came (a stream started again, a backlog dropped),
 *  and a line across it would draw what never happened. */
export const GAP_S = 0.2

/** The plotted history: one time axis; per station a frequency and a voltage series; per line end a
 *  current and a loading series; per injection a P and a Q series; and the latest SCADA scan, one
 *  value per SCADA point of the layout. Kept in a ref, outside React: 50 frames a second must not mean
 *  50 renders a second. */
export type LiveBuffer = {
  t: number[]
  f: (number | null)[][]
  v: (number | null)[][]
  i: (number | null)[][]
  loading: (number | null)[][]
  p: (number | null)[][]
  q: (number | null)[][]
  scan: LiveScan | null
}

/** The buffer's series, each a quantity of one kind of thing. */
export type Quantity = Exclude<keyof LiveBuffer, 't' | 'scan'>

const series = (n: number) => Array.from({ length: n }, () => [] as (number | null)[])
const empty = (stations = 0, ends = 0, injections = 0): LiveBuffer => ({
  t: [],
  f: series(stations),
  v: series(stations),
  i: series(ends),
  loading: series(ends),
  p: series(injections),
  q: series(injections),
  scan: null,
})

/** Which wire field fills which series. */
const FIELDS: [Quantity, keyof LiveFeed['samples']][] = [
  ['f', 'f_hz'],
  ['v', 'v_pu'],
  ['i', 'i_a'],
  ['loading', 'loading'],
  ['p', 'p_mw'],
  ['q', 'q_mvar'],
]

/**
 * The live grid feed (`/api/cim-live/ws`): every frame of the RT sim, as each station's voltage and
 * frequency, each line end's current and loading, and each generator's and load's power; and, every
 * couple of seconds, the latest SCADA scan (`buffer.scan`, one value per point of `scada`). The samples go into `buffer` and wake `subscribe`rs (the charts, the map's colours) at
 * most once per animation frame; React renders only when the stations change, and once a second for
 * `samplesPerSecond`, what the page measured arriving, and `lagSeconds`, how far behind real time the
 * newest frame is by the server's clock. Two frames more than `GAP_S` apart are not joined.
 */
export function useLiveFeed() {
  const [stations, setStations] = useState<LiveStation[]>([])
  const [lineEnds, setLineEnds] = useState<LiveLineEnd[]>([])
  const [injections, setInjections] = useState<LiveInjection[]>([])
  const [scada, setScada] = useState<LiveScadaPoint[]>([])
  const [samplesPerSecond, setSamplesPerSecond] = useState(0)
  const buffer = useRef<LiveBuffer>(empty(0))
  const listeners = useRef(new Set<() => void>())
  const scheduled = useRef(false)
  const arrivals = useRef<{ at: number; n: number }[]>([])
  const lag = useRef(0)
  const [lagSeconds, setLagSeconds] = useState(0)

  const notify = useCallback(() => {
    if (scheduled.current) return
    scheduled.current = true
    requestAnimationFrame(() => {
      scheduled.current = false
      listeners.current.forEach((listener) => listener())
    })
  }, [])

  const onMessage = useCallback(
    (feed: LiveFeed) => {
      if (feed.layout) {
        const { stations, line_ends = [], injections = [], scada = [] } = feed.layout
        buffer.current = empty(stations.length, line_ends.length, injections.length)
        setStations(stations)
        setLineEnds(line_ends)
        setInjections(injections)
        setScada(scada)
      }
      const buf = buffer.current
      if (feed.scan) buf.scan = feed.scan
      const { t } = feed.samples
      if (feed.lag_s !== null && feed.lag_s !== undefined) lag.current = feed.lag_s
      for (let i = 0; i < t.length; i++) {
        const last = buf.t[buf.t.length - 1]
        if (last !== undefined && t[i] - last > GAP_S) {
          // A row of nulls between them: uPlot (spanGaps off) breaks every line there.
          buf.t.push((last + t[i]) / 2)
          for (const [quantity] of FIELDS) buf[quantity].forEach((series) => series.push(null))
        }
        buf.t.push(t[i])
        for (const [quantity, field] of FIELDS) {
          const rows = (feed.samples[field] ?? []) as (number | null)[][]
          rows[i]?.forEach((value, s) => buf[quantity][s]?.push(value))
        }
      }
      const cut = buf.t.findIndex((x) => x >= (buf.t[buf.t.length - 1] ?? 0) - WINDOW_S)
      if (cut > 0) {
        buf.t.splice(0, cut)
        for (const [quantity] of FIELDS) buf[quantity].forEach((series) => series.splice(0, cut))
      }
      arrivals.current.push({ at: performance.now(), n: t.length })
      notify()
    },
    [notify],
  )

  const { status, connected } = useServerSocket<LiveFeed>(CIM_LIVE_WS_PATH, { onMessage })

  // What arrives, per second, over the last RATE_WINDOW_S: the page's own measure of the feed.
  useEffect(() => {
    const timer = setInterval(() => {
      const since = performance.now() - RATE_WINDOW_S * 1000
      arrivals.current = arrivals.current.filter((a) => a.at >= since)
      setSamplesPerSecond(arrivals.current.reduce((sum, a) => sum + a.n, 0) / RATE_WINDOW_S)
      setLagSeconds(lag.current)
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  const subscribe = useCallback((listener: () => void) => {
    listeners.current.add(listener)
    return () => {
      listeners.current.delete(listener)
    }
  }, [])

  return { stations, lineEnds, injections, scada, buffer, subscribe, samplesPerSecond, lagSeconds, status, connected }
}
