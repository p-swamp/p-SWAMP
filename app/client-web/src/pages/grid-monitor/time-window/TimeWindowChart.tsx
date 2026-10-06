import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'

import { PLOT_BACKGROUND } from '../palette'
import type { ChannelInfo, WindowBuffer } from './useTimeWindowSocket'

/**
 * Trace colours for when each channel is to be told apart. Enough to keep a
 * dozen distinguishable, and bright enough for the dark plot background — the
 * role `pg.intColor` plays in the Qt time window plot.
 */
const TRACE_COLORS = [
  '#60a5fa',
  '#f87171',
  '#34d399',
  '#fbbf24',
  '#a78bfa',
  '#22d3ee',
  '#f472b6',
  '#a3e635',
  '#38bdf8',
  '#fb923c',
  '#818cf8',
  '#fb7185',
]

const AXIS_COLOR = '#b9c8c8'
const GRID_COLOR = 'rgba(255, 255, 255, 0.08)'

/** A moment worth marking on the time axis, e.g. when an alarm was raised. */
export type TimeMarker = { t: number; label: string }

/**
 * A streaming multi-channel chart.
 *
 * uPlot on a canvas, driven imperatively: the data arrives ten times a second
 * over a window of a few thousand points per channel, which is well past what
 * SVG or a React charting library will do comfortably. Redraws come through the
 * hook's `subscribe`, not through props, so **no React render happens on the
 * data path at all** — this component re-renders only when the set of channels
 * changes and the plot has to be rebuilt.
 *
 * `strokeOf` and `markers` follow the same rule from the other side: they are
 * read when the plot draws, not baked in when it is built, so a station changing
 * island recolours its trace on the next batch of samples instead of tearing the
 * plot down.
 */
export function TimeWindowChart({
  buffer,
  subscribe,
  channels,
  height = 320,
  legend = true,
  strokeOf,
  markers,
  yLabel,
}: {
  buffer: React.RefObject<WindowBuffer>
  subscribe: (notify: () => void) => () => void
  /** Only used to detect a shape change; the values are read from `buffer`. */
  channels: ChannelInfo[]
  height?: number
  /** The live legend under the plot. Worth its height for a handful of named
   *  traces; not for every station's frequency at once. */
  legend?: boolean
  /** A trace's colour. Defaults to a colour per trace. */
  strokeOf?: (channel: ChannelInfo) => string
  markers?: TimeMarker[]
  yLabel?: string
}) {
  const container = useRef<HTMLDivElement | null>(null)
  const plot = useRef<uPlot | null>(null)

  // Read by the plot whenever it draws; updated after commit, never in render.
  const strokeRef = useRef(strokeOf)
  const markersRef = useRef(markers)
  useEffect(() => {
    strokeRef.current = strokeOf
    markersRef.current = markers
    plot.current?.redraw(false)
  }, [strokeOf, markers])

  // Build (or rebuild) the plot when the channel set changes.
  useEffect(() => {
    const node = container.current
    const buf = buffer.current
    if (!node || !buf || channels.length === 0) return

    plot.current?.destroy()
    plot.current = new uPlot(
      {
        width: node.clientWidth || 640,
        height,
        // Times are epoch seconds, uPlot's native x scale, so the axis formats
        // as wall-clock time with no extra configuration.
        series: [
          {},
          ...channels.map((channel, i) => ({
            label: channel.label,
            // uPlot asks again on every draw, which is what lets the colour
            // follow something that changes — see strokeOf above.
            stroke: () =>
              strokeRef.current?.(channel) ?? TRACE_COLORS[i % TRACE_COLORS.length],
            width: 1.5,
            // A missing sample is null; joining across it would draw a straight
            // line through data that was never measured.
            spanGaps: false,
          })),
        ],
        axes: [
          {
            stroke: AXIS_COLOR,
            grid: { stroke: GRID_COLOR },
            ticks: { stroke: GRID_COLOR },
          },
          {
            stroke: AXIS_COLOR,
            grid: { stroke: GRID_COLOR },
            ticks: { stroke: GRID_COLOR },
            label: yLabel,
            labelSize: yLabel ? 18 : undefined,
            // Room for "50.005": the default clips the leading digit.
            size: 58,
          },
        ],
        legend: { show: legend, live: true },
        cursor: { drag: { x: true, y: false } },
        hooks: {
          draw: [
            (u) => {
              const list = markersRef.current
              if (!list?.length) return
              const { ctx, bbox } = u
              ctx.save()
              ctx.strokeStyle = '#ffffff'
              ctx.fillStyle = '#ffffff'
              ctx.lineWidth = devicePixelRatio
              ctx.font = `${11 * devicePixelRatio}px sans-serif`
              ctx.textBaseline = 'top'
              for (const marker of list) {
                const x = u.valToPos(marker.t, 'x', true)
                if (x < bbox.left || x > bbox.left + bbox.width) continue
                ctx.beginPath()
                ctx.moveTo(x, bbox.top)
                ctx.lineTo(x, bbox.top + bbox.height)
                ctx.stroke()
                ctx.fillText(marker.label, x + 4 * devicePixelRatio, bbox.top + 2)
              }
              ctx.restore()
            },
          ],
        },
      },
      [buf.t, ...buf.series] as unknown as uPlot.AlignedData,
      node,
    )

    return () => {
      plot.current?.destroy()
      plot.current = null
    }
  }, [buffer, channels, height, legend, yLabel])

  // Redraw on each new batch of samples. Outside React's render cycle entirely.
  useEffect(
    () =>
      subscribe(() => {
        const buf = buffer.current
        if (!plot.current || !buf) return
        // A message may arrive between the channel set changing and the plot
        // being rebuilt; drawing mismatched series would throw inside uPlot.
        if (buf.series.length !== plot.current.series.length - 1) return
        plot.current.setData(
          [buf.t, ...buf.series] as unknown as uPlot.AlignedData,
        )
      }),
    [subscribe, buffer],
  )

  // Follow container width; the panel this sits in is responsive.
  useEffect(() => {
    const node = container.current
    if (!node) return
    const observer = new ResizeObserver(() => {
      if (plot.current && node.clientWidth > 0) {
        plot.current.setSize({ width: node.clientWidth, height })
      }
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [height])

  return (
    <div
      ref={container}
      // The Qt plots' background, in light and dark mode alike: the trace and
      // island colours are chosen against it.
      className="w-full overflow-hidden rounded-sm py-1 text-[#dfe8e8]"
      style={{ background: PLOT_BACKGROUND }}
    />
  )
}
