import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

import { stationColor } from './colors'
import type { LiveBuffer, LiveStation } from './useLiveFeed'


/**
 * One live chart: every station a line, `quantity` of `buffer` against time, the last 30 s. uPlot on a
 * canvas, driven imperatively: the plot is built when the stations change, and redrawn through
 * `subscribe` (at most once per animation frame), never through a React render. `highlight` (a
 * station's index) is drawn on top and the others faded.
 */
export function LiveChart({
  title,
  unit,
  quantity,
  stations,
  buffer,
  subscribe,
  highlight,
  height = 220,
}: {
  title: string
  unit: string
  quantity: 'f' | 'v'
  stations: LiveStation[]
  buffer: React.RefObject<LiveBuffer>
  subscribe: (listener: () => void) => () => void
  highlight: number | null
  height?: number
}) {
  const container = useRef<HTMLDivElement | null>(null)
  const plot = useRef<uPlot | null>(null)

  useEffect(() => {
    const node = container.current
    if (!node || stations.length === 0) return
    const data = () => [buffer.current.t, ...buffer.current[quantity]] as unknown as uPlot.AlignedData
    plot.current?.destroy()
    plot.current = new uPlot(
      {
        title,
        width: node.clientWidth || 640,
        height,
        series: [
          {},
          ...stations.map((station, i) => ({
            label: station.name,
            stroke: stationColor(i),
            width: 1.25,
            spanGaps: false,
            value: (_: uPlot, v: number | null) => (v === null ? '—' : v.toFixed(4)),
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
  }, [buffer, height, quantity, stations, title, unit])

  useEffect(
    () =>
      subscribe(() => {
        const p = plot.current
        const buf = buffer.current
        if (!p || buf[quantity].length !== p.series.length - 1) return
        p.setData([buf.t, ...buf[quantity]] as unknown as uPlot.AlignedData)
      }),
    [buffer, quantity, subscribe],
  )

  useEffect(() => {
    const p = plot.current
    if (!p) return
    // uPlot's own focus: the highlighted series on top, the others faded; none: all as they are.
    p.setSeries(highlight === null ? null : highlight + 1, { focus: true })
  }, [highlight, stations])

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
