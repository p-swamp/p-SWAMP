import { useEffect, useMemo, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

import { stationColor } from './colors'
import type { LiveBuffer, Quantity } from './useLiveFeed'


/**
 * One live chart: `quantity` of `buffer` against time, the last 30 s, a line per series: every one, or
 * those `pick` lists (indices into the quantity's series), labelled by `labels` (one per series). uPlot on a
 * canvas, driven imperatively: the plot is built when the stations change, and redrawn through
 * `subscribe` (at most once per animation frame), never through a React render. `highlight` (a
 * series' index) is drawn on top and the others faded.
 */
export function LiveChart({
  title,
  unit,
  quantity,
  labels,
  pick,
  buffer,
  subscribe,
  highlight = null,
  height = 220,
  digits = 4,
}: {
  title: string
  unit: string
  quantity: Quantity
  labels: string[]
  pick?: number[]
  buffer: React.RefObject<LiveBuffer>
  subscribe: (listener: () => void) => () => void
  highlight?: number | null
  height?: number
  digits?: number
}) {
  const container = useRef<HTMLDivElement | null>(null)
  const plot = useRef<uPlot | null>(null)

  const shown = useMemo(() => pick ?? labels.map((_, i) => i), [labels, pick])
  const key = shown.join(',')

  useEffect(() => {
    const node = container.current
    if (!node || shown.length === 0) return
    const data = () => [buffer.current.t, ...shown.map((i) => buffer.current[quantity][i] ?? [])] as unknown as uPlot.AlignedData
    plot.current?.destroy()
    plot.current = new uPlot(
      {
        title,
        width: node.clientWidth || 640,
        height,
        series: [
          {},
          ...shown.map((i) => ({
            label: labels[i] ?? String(i),
            stroke: stationColor(i),
            width: 1.25,
            spanGaps: false,
            value: (_: uPlot, v: number | null) => (v === null ? '—' : v.toFixed(digits)),
          })),
        ],
        axes: [
          { stroke: 'currentColor', grid: { stroke: 'rgba(128,128,128,0.15)' } },
          { stroke: 'currentColor', grid: { stroke: 'rgba(128,128,128,0.15)' }, label: unit, size: 60 },
        ],
        focus: { alpha: 0.2 },
        legend: { live: false },
        cursor: { drag: { x: false, y: false }, focus: { prox: 16 } },
      },
      data(),
      node,
    )
    return () => {
      plot.current?.destroy()
      plot.current = null
    }
    // `key` stands for `shown`: a new array with the same series is the same chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buffer, digits, height, quantity, key, labels, title, unit])

  useEffect(
    () =>
      subscribe(() => {
        const p = plot.current
        const buf = buffer.current
        if (!p || shown.length !== p.series.length - 1 || shown.some((i) => !buf[quantity][i])) return
        p.setData([buf.t, ...shown.map((i) => buf[quantity][i])] as unknown as uPlot.AlignedData)
      }),
    [buffer, quantity, shown, subscribe],
  )

  useEffect(() => {
    const p = plot.current
    if (!p) return
    // uPlot's own focus: the highlighted series on top, the others faded; none: all as they are.
    const at = highlight === null ? -1 : shown.indexOf(highlight)
    p.setSeries(at < 0 ? null : at + 1, { focus: true })
  }, [highlight, shown])

  useEffect(() => {
    const node = container.current
    if (!node) return
    const observer = new ResizeObserver(() => {
      if (plot.current && node.clientWidth > 0) plot.current.setSize({ width: node.clientWidth, height })
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [height])

  return <div ref={container} className="w-full" data-testid={`chart-${quantity}`} />
}
