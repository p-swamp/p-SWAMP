import { useCallback, useEffect, useRef, useState } from 'react'

import type { Wire } from '@/api/wire'
import { CIM_LIVE_WS_PATH } from '@/lib/servers'
import { useServerSocket } from '@/hooks/useServerSocket'

export type LiveFeed = Wire['LiveFeed']
export type LiveStation = Wire['LiveStation']
export type LiveLineEnd = Wire['LiveLineEnd']
export type LiveInjection = Wire['LiveInjection']

/** Seconds of history the charts show. */
export const WINDOW_S = 30
/** Seconds the received-samples rate is measured over. */
const RATE_WINDOW_S = 2

/** The plotted history: one time axis; per station a frequency and a voltage series; per line end a
 *  current and a loading series; per injection a P and a Q series. Kept in a ref, outside React: 50
 *  frames a second must not mean 50 renders a second. */
export type LiveBuffer = {
  t: number[]
  f: (number | null)[][]
  v: (number | null)[][]
  i: (number | null)[][]
  loading: (number | null)[][]
  p: (number | null)[][]
  q: (number | null)[][]
}

/** The buffer's series, each a quantity of one kind of thing. */
export type Quantity = Exclude<keyof LiveBuffer, 't'>

const series = (n: number) => Array.from({ length: n }, () => [] as (number | null)[])
const empty = (stations = 0, ends = 0, injections = 0): LiveBuffer => ({
  t: [],
  f: series(stations),
  v: series(stations),
  i: series(ends),
  loading: series(ends),
  p: series(injections),
  q: series(injections),
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
 * frequency, each line end's current and loading, and each generator's and load's power. The samples go into `buffer` and wake `subscribe`rs (the charts, the map's colours) at
 * most once per animation frame; React renders only when the stations change, and once a second for
 * `samplesPerSecond`, what the page measured arriving.
 */
export function useLiveFeed() {
  const [stations, setStations] = useState<LiveStation[]>([])
  const [lineEnds, setLineEnds] = useState<LiveLineEnd[]>([])
  const [injections, setInjections] = useState<LiveInjection[]>([])
  const [samplesPerSecond, setSamplesPerSecond] = useState(0)
  const buffer = useRef<LiveBuffer>(empty(0))
  const listeners = useRef(new Set<() => void>())
  const scheduled = useRef(false)
  const arrivals = useRef<{ at: number; n: number }[]>([])

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
        const { stations, line_ends = [], injections = [] } = feed.layout
        buffer.current = empty(stations.length, line_ends.length, injections.length)
        setStations(stations)
        setLineEnds(line_ends)
        setInjections(injections)
      }
      const buf = buffer.current
      const { t } = feed.samples
      for (let i = 0; i < t.length; i++) {
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
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  const subscribe = useCallback((listener: () => void) => {
    listeners.current.add(listener)
    return () => {
      listeners.current.delete(listener)
    }
  }, [])

  return { stations, lineEnds, injections, buffer, subscribe, samplesPerSecond, status, connected }
}
