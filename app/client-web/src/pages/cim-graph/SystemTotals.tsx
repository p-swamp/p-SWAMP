import { useEffect, useRef } from 'react'

import { scadaTotals, scanTime } from './scada'
import type { LiveBuffer, LiveScadaPoint } from './useLiveFeed'

/** How often the totals are rewritten: a reader need not follow 50 frames a second. */
const EVERY_MS = 250

/**
 * The system's generation and load, MW, as the latest SCADA scan has them: the sums of its generators'
 * and its loads' active power (the grid's PMUs need not measure power; its SCADA does). Written into
 * the DOM from the live buffer, four times a second, never through a React render.
 */
export function SystemTotals({
  scada,
  buffer,
  subscribe,
}: {
  scada: LiveScadaPoint[]
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
      const { generation, load } = scadaTotals(buffer.current, scada)
      const mw = (x: number | null) => (x === null ? '—' : `${x.toFixed(0)} MW`)
      const at = scanTime(buffer.current)
      text.current.textContent = `Generation ${mw(generation)} · load ${mw(load)}${at ? ` (SCADA, ${at})` : ''}`
    })
  }, [buffer, scada, subscribe])
  return (
    <span ref={text} data-testid="system-totals">
      Generation — · load —
    </span>
  )
}
