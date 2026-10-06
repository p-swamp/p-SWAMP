import { useMemo } from 'react'

import { ISLAND_COLORS, PLOT_BACKGROUND } from '../palette'
import type { Phasor } from './usePhasorsSocket'

// The internal coordinate space. Fixed, because the viewBox scales it to
// whatever CSS size the panel asks for — so a compact dock dial and a full-size
// one share every bit of geometry below.
const VIEW = 420
const CENTER = VIEW / 2
const RADIUS = VIEW / 2 - 34
/** Label size in view units at full size; scaled up as the dial shrinks so text
 *  stays about as legible on screen either way. */
const LABEL_PX = 9
/** Below this rendered size the station labels are left out: scaled up to stay
 *  legible they no longer fit between the arrow tips and the edge. The Qt plot
 *  names no stations at all, only the islands in its legend. */
const MIN_SIZE_FOR_LABELS = 300
/** Magnitude rings and angle spokes, as `PhasorBasePlot` draws its grid: four
 *  circles, and a line through the centre every 45 degrees. */
const RINGS = 4
const SPOKE_DEGREES = 45
const GRID_COLOR = '#808080'

/**
 * Voltage phasors on a polar dial, after the Qt phasor plot: the same dark
 * background, the same grid, an open arrowhead on each phasor, and each phasor
 * in the colour of the island its station is in.
 *
 * Hand-drawn SVG: no charting library draws a polar plot with arrowheads, and at
 * 44 elements updating five times a second there is nothing to optimise — the
 * wrapper would be larger than the drawing code.
 */
export function PhasorDial({
  phasors,
  magRef,
  angRef,
  equalLengths,
  rotateToMean,
  size = VIEW,
}: {
  phasors: Phasor[]
  magRef: number | null
  angRef: number | null
  /** Draw every phasor the same length, so only the angles differ — p-SWAMP's
   *  `normalize_length`. Magnitudes across the grid vary by a few percent, so
   *  scaling by them makes the angle spread hard to read. */
  equalLengths: boolean
  rotateToMean: boolean
  /** Rendered size in CSS pixels. Geometry is unaffected; the viewBox scales. */
  size?: number
}) {
  const arrows = useMemo(() => {
    const rotation = rotateToMean ? (angRef ?? 0) : 0

    return phasors
      .filter((p) => p.mag !== null && p.ang !== null && (equalLengths || magRef))
      .map((p) => {
        const r = equalLengths
          ? RADIUS
          : (Math.min(p.mag as number, magRef as number) / (magRef as number)) * RADIUS
        const theta = (p.ang as number) - rotation
        const island = (p.island ?? 0) % ISLAND_COLORS.length
        // SVG y grows downward, so the sine is negated to put 0 rad at the right
        // and positive angles anticlockwise, as a phasor diagram expects.
        return {
          station: p.station,
          island,
          color: ISLAND_COLORS[island],
          x: CENTER + r * Math.cos(theta),
          y: CENTER - r * Math.sin(theta),
        }
      })
  }, [phasors, magRef, angRef, equalLengths, rotateToMean])

  return (
    <svg
      viewBox={`0 0 ${VIEW} ${VIEW}`}
      style={{ height: size, maxWidth: size, background: PLOT_BACKGROUND }}
      className="mx-auto w-full rounded-sm"
      role="img"
      aria-label="Voltage phasors by station"
    >
      <defs>
        {/* One marker per colour: SVG markers cannot inherit the line's stroke
            in a way all browsers honour, so each island gets its own. */}
        {ISLAND_COLORS.map((color, i) => (
          <marker
            key={i}
            id={`phasor-head-${i}`}
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10" fill="none" stroke={color} strokeWidth="2" />
          </marker>
        ))}
      </defs>

      {Array.from({ length: RINGS }, (_, i) => (
        <circle
          key={i}
          cx={CENTER}
          cy={CENTER}
          r={(RADIUS * (i + 1)) / RINGS}
          fill="none"
          stroke={GRID_COLOR}
          strokeWidth={0.75}
        />
      ))}

      {Array.from({ length: 360 / SPOKE_DEGREES }, (_, i) => {
        const theta = (i * SPOKE_DEGREES * Math.PI) / 180
        return (
          <line
            key={i}
            x1={CENTER}
            y1={CENTER}
            x2={CENTER + RADIUS * Math.cos(theta)}
            y2={CENTER - RADIUS * Math.sin(theta)}
            stroke={GRID_COLOR}
            strokeWidth={0.75}
          />
        )
      })}

      {/* The main system first, so a separated island is drawn over it rather
          than under forty arrows of the grid it left. */}
      {arrows
        .slice()
        .sort((a, b) => a.island - b.island)
        .map((arrow) => (
          <line
            key={arrow.station}
            x1={CENTER}
            y1={CENTER}
            x2={arrow.x}
            y2={arrow.y}
            stroke={arrow.color}
            strokeWidth={2}
            markerEnd={`url(#phasor-head-${arrow.island})`}
          />
        ))}

      {/* Labels last so they sit above the arrows. Only the outermost few are
          worth naming; 44 labels on one dial is unreadable. */}
      {(size >= MIN_SIZE_FOR_LABELS ? arrows : [])
        .slice()
        .sort(
          (a, b) =>
            Math.hypot(b.x - CENTER, b.y - CENTER) -
            Math.hypot(a.x - CENTER, a.y - CENTER),
        )
        .slice(0, 8)
        .map((arrow) => (
          <text
            key={`label-${arrow.station}`}
            x={arrow.x}
            y={arrow.y}
            dx={arrow.x >= CENTER ? 4 : -4}
            dy={arrow.y >= CENTER ? 10 : -4}
            textAnchor={arrow.x >= CENTER ? 'start' : 'end'}
            fontSize={LABEL_PX * (VIEW / size)}
            fill="#dfe8e8"
            opacity={0.75}
          >
            {arrow.station}
          </text>
        ))}
    </svg>
  )
}
