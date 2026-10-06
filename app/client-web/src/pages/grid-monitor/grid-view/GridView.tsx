import { useEffect, useRef, useState } from 'react'

import { islandName } from '../palette'
import {
  createGridRenderer,
  type GridLayers,
  type GridRenderer,
  type GridViewData,
  type GridViewMode,
  type Hover,
} from './renderer'
import type { Scene } from './scene'

/** A source of each station's present frequency that changes too often to be a
 *  prop: the view subscribes, and reads when told to. */
export type LiveFrequencies = {
  subscribe: (notify: () => void) => () => void
  /** Station name to frequency in Hz, for the stations that have one. */
  read: () => Map<string, number>
}

/**
 * The grid, drawn the way p-SWAMP's Qt grid view draws it: country outlines on
 * the map plane, the network floating above it on its bus stems, coloured by
 * island, each island raised or lowered by how far its frequency is off nominal.
 *
 * This component is only the React edge of `renderer.ts`. It creates the
 * renderer for a scene and forwards what changes; the drawing, the camera and
 * the pointer are all in there, outside the render cycle. The one thing it owns
 * is the hover label, which is ordinary DOM.
 */
export function GridView({
  scene,
  data,
  layers,
  mode,
  resetSignal,
  frequencies,
}: {
  scene: Scene
  data: GridViewData
  layers: GridLayers
  mode: GridViewMode
  /** Change this to send the camera back to its opening view. */
  resetSignal: number
  /** Optional. With it the islands move with the measurement stream; without,
   *  they sit at the mean frequency the detector last reported. */
  frequencies?: LiveFrequencies
}) {
  const canvas = useRef<HTMLCanvasElement | null>(null)
  const renderer = useRef<GridRenderer | null>(null)
  const [hover, setHover] = useState<Hover>(null)

  useEffect(() => {
    if (!canvas.current) return
    const created = createGridRenderer(canvas.current, scene, setHover)
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

  useEffect(() => {
    if (!frequencies) {
      renderer.current?.setFrequencies(null)
      return
    }
    const push = () => renderer.current?.setFrequencies(frequencies.read())
    push()
    return frequencies.subscribe(push)
  }, [scene, frequencies])

  const island = hover ? (data.islandOf.get(hover.station) ?? 0) : 0
  const frequency = data.islandFreq.get(island)

  return (
    <div className="relative size-full overflow-hidden">
      <canvas
        ref={canvas}
        className="block size-full"
        role="img"
        aria-label="Nordic 44 grid, coloured by detected island"
      />
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
