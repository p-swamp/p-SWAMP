import { useEffect, useRef, useState } from 'react'

import { islandName } from '../palette'
import type { FieldKind } from './field'
import type { LiveValues } from './liveValues'
import {
  createGridRenderer,
  type GridLayers,
  type GridRenderer,
  type GridViewData,
  type GridViewMode,
  type Hover,
} from './renderer'
import type { Scene } from './scene'

/**
 * The grid, drawn the way p-SWAMP's Qt grid view draws it: country outlines on
 * the map plane, the network floating above it on its bus stems, coloured by
 * island, each island raised or lowered by how far its frequency is off nominal.
 *
 * This component is only the React edge of `renderer.ts`. It creates the
 * renderer for a scene and forwards what changes; the camera, the pointer and
 * the animation are all in there, outside the render cycle, and the picture is
 * WebGL (`glPainter.ts`). The one thing it owns is the hover label, which is
 * ordinary DOM.
 */
export function GridView({
  scene,
  data,
  layers,
  mode,
  resetSignal,
  field,
  relief,
  frequencies,
  voltages,
}: {
  scene: Scene
  data: GridViewData
  layers: GridLayers
  mode: GridViewMode
  /** Change this to send the camera back to its opening view. */
  resetSignal: number
  /** The quantity to spread over the grid as a heat map or surface, if any. */
  field: FieldKind | null
  /** How far a field lifts a bus in 3D, as a multiple of the usual. */
  relief: number
  /** Each station's frequency in Hz. Optional: with it the islands move with
   *  the measurement stream; without, they sit at the mean frequency the
   *  detector last reported, and there is no frequency field to show. */
  frequencies?: LiveValues
  /** Each station's voltage, per unit. Only the voltage field reads it. */
  voltages?: LiveValues
}) {
  const container = useRef<HTMLDivElement | null>(null)
  const renderer = useRef<GridRenderer | null>(null)
  const [hover, setHover] = useState<Hover>(null)
  const [unavailable, setUnavailable] = useState(false)

  useEffect(() => {
    if (!container.current) return
    let created: GridRenderer
    try {
      created = createGridRenderer(container.current, scene, setHover)
    } catch (error) {
      // No WebGL: a blocked GPU, a remote desktop without one. Say so in the
      // view rather than leaving it blank. Deferred, so the state is not set
      // synchronously in the effect body.
      console.error('the grid view could not start', error)
      queueMicrotask(() => setUnavailable(true))
      return
    }
    renderer.current = created
    return () => {
      created.destroy()
      renderer.current = null
    }
  }, [scene])

  // Declared after the effect above, so on a new scene these run against the
  // renderer it has just created. `scene` is a dependency for that reason only.
  useEffect(() => renderer.current?.setData(data), [scene, data])
  useEffect(() => renderer.current?.setLayers(layers), [scene, layers])
  useEffect(() => renderer.current?.setMode(mode), [scene, mode])
  useEffect(() => renderer.current?.resetView(), [scene, resetSignal])
  useEffect(() => renderer.current?.setField(field, relief), [scene, field, relief])

  useEffect(() => {
    if (!frequencies) {
      renderer.current?.setFrequencies(null)
      return
    }
    const push = () => renderer.current?.setFrequencies(frequencies.read())
    push()
    return frequencies.subscribe(push)
  }, [scene, frequencies])

  useEffect(() => {
    if (!voltages) {
      renderer.current?.setVoltages(null)
      return
    }
    const push = () => renderer.current?.setVoltages(voltages.read())
    push()
    return voltages.subscribe(push)
  }, [scene, voltages])

  const island = hover ? (data.islandOf.get(hover.station) ?? 0) : 0
  const frequency = data.islandFreq.get(island)

  return (
    <div className="relative size-full overflow-hidden">
      {/* The renderer puts its canvases in here, and takes them out again. */}
      <div ref={container} className="absolute inset-0" />
      {unavailable && (
        <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-white/70">
          The grid view is drawn with WebGL, which this browser could not
          provide.
        </div>
      )}
      {hover && (
        <div
          className="pointer-events-none absolute z-10 -translate-y-full rounded bg-black/70 px-2 py-1 text-xs whitespace-nowrap text-white"
          style={{ left: hover.x + 10, top: hover.y - 8 }}
        >
          <span className="font-mono font-medium">{hover.station}</span>
          {data.assessed && (
            <span className="ml-2 text-white/70">
              {islandName(island)}
              {frequency !== undefined && ` · ${frequency.toFixed(3)} Hz`}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
