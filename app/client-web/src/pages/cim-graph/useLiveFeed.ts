import { useCallback, useEffect, useRef, useState } from 'react'

import type { Wire } from '@/api/wire'
import { CIM_LIVE_WS_PATH } from '@/lib/servers'
import { useServerSocket } from '@/hooks/useServerSocket'

export type LiveFeed = Wire['LiveFeed']
export type LiveStation = Wire['LiveStation']

/** Seconds of history the charts show. */
export const WINDOW_S = 30
/** Seconds the received-samples rate is measured over. */
const RATE_WINDOW_S = 2

/** The plotted history: one time axis, and per station a frequency and a voltage series. Kept in a
 *  ref, outside React: 50 frames a second must not mean 50 renders a second. */
export type LiveBuffer = {
  t: number[]
  f: (number | null)[][]
  v: (number | null)[][]
}

const empty = (stations: number): LiveBuffer => ({
  t: [],
  f: Array.from({ length: stations }, () => []),
  v: Array.from({ length: stations }, () => []),
})

/**
 * The live grid feed (`/api/cim-live/ws`): every frame of the RT sim, as each station's voltage and
 * frequency. The samples go into `buffer` and wake `subscribe`rs (the charts, the map's colours) at
 * most once per animation frame; React renders only when the stations change, and once a second for
 * `samplesPerSecond`, what the page measured arriving.
 */
export function useLiveFeed() {
  const [stations, setStations] = useState<LiveStation[]>([])
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
        buffer.current = empty(feed.layout.stations.length)
        setStations(feed.layout.stations)
      }
      const buf = buffer.current
      const { t, f_hz, v_pu } = feed.samples
      for (let i = 0; i < t.length; i++) {
        buf.t.push(t[i])
        f_hz[i].forEach((value, s) => buf.f[s]?.push(value))
        v_pu[i].forEach((value, s) => buf.v[s]?.push(value))
      }
      const cut = buf.t.findIndex((x) => x >= (buf.t[buf.t.length - 1] ?? 0) - WINDOW_S)
      if (cut > 0) {
        buf.t.splice(0, cut)
        buf.f.forEach((series) => series.splice(0, cut))
        buf.v.forEach((series) => series.splice(0, cut))
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

  return { stations, buffer, subscribe, samplesPerSecond, status, connected }
}
