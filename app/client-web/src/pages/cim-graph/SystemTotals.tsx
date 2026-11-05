import { useEffect, useRef } from 'react'

import type { LiveBuffer, LiveInjection } from './useLiveFeed'

/** How often the totals are rewritten: a reader need not follow 50 frames a second. */
const EVERY_MS = 250

/** The newest value of each of ``kind``'s injections' P series, summed (MW); null: none is known. */
function total(buffer: LiveBuffer, injections: LiveInjection[], kind: LiveInjection['kind']): number | null {
  let sum: number | null = null
  injections.forEach((injection, i) => {
    const series = buffer.p[i]
    const value = series?.[series.length - 1]
    if (injection.kind === kind && value !== null && value !== undefined) sum = (sum ?? 0) + value
  })
  return sum
}

/**
 * The system's generation and load, MW, as the simulation measures them now: the sums of its
 * generators' and its loads' active power. Written into the DOM from the live buffer, four times a
 * second, never through a React render.
 */
export function SystemTotals({
  injections,
  buffer,
  subscribe,
}: {
  injections: LiveInjection[]
  buffer: React.RefObject<LiveBuffer>
  subscribe: (listener: () => void) => () => void
}) {
  const text = useRef<HTMLSpanElement | null>(null)
  useEffect(() => {
    let last = 0
    return subscribe(() => {
      const now = performance.now()
      if (now - last < EVERY_MS || !text.current) return
      last = now
      const generation = total(buffer.current, injections, 'generator')
      const load = total(buffer.current, injections, 'load')
      const mw = (x: number | null) => (x === null ? '—' : `${x.toFixed(0)} MW`)
      text.current.textContent = `Generation ${mw(generation)} · load ${mw(load)}`
    })
  }, [buffer, injections, subscribe])
  return (
    <span ref={text} data-testid="system-totals">
      Generation — · load —
    </span>
  )
}
