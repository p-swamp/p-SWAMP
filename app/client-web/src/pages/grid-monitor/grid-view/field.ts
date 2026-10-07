import type { Scene } from './scene'
import { triangulate } from './triangulate'

/** The quantities the grid view can spread over the map. */
export type FieldKind = 'frequency' | 'voltage'

/**
 * What each field shows, and over what range its colours run.
 *
 * `limit` is the deviation at which the colour is fully saturated, and
 * `liftPerUnit` how far a bus rises in the 3D view for one unit of deviation.
 *
 * - **frequency** is the Qt "Frequency heat map": each bus's frequency *minus
 *   the mean of all of them*, saturating at 35 mHz (`lims=[-0.035, 0.035]`). The
 *   lift is the one the islanding view uses, five units per hertz.
 * - **voltage** is the Qt voltage heat map as it was evidently meant: per-unit
 *   magnitude around 1.0, saturating at 0.9 and 1.1 (`lims=[0.9, 1.1]`,
 *   `z_offset=1`). The Qt one feeds those limits volts, which is why it is
 *   switched off there; `Voltage3DLayer` does the per-unit division.
 */
export const FIELDS: Record<
  FieldKind,
  {
    label: string
    limit: number
    liftPerUnit: number
    /** The two ends of the colour scale, and what it is a scale *of*. */
    low: string
    high: string
    scaleOf: string
  }
> = {
  frequency: {
    label: 'Frequency heat map',
    limit: 0.035,
    liftPerUnit: 5,
    low: '−35 mHz',
    high: '+35 mHz',
    scaleOf: 'frequency, from the grid mean',
  },
  voltage: {
    label: 'Voltage heat map',
    limit: 0.1,
    liftPerUnit: 10,
    low: '0.90 pu',
    high: '1.10 pu',
    scaleOf: 'voltage, of nominal',
  },
}

/** `HeatMap` pads the bus bounding box by this share of its *width* on every
 *  side, and pins the four corners of the padded box to "no deviation". */
const PADDING = 0.2

/**
 * The mesh a field is drawn on: the buses, four corner anchors around them,
 * and the triangles between.
 *
 * It is the Qt heat map's interpolation, kept as geometry instead of being
 * baked into an image. There, `scipy.griddata(method='linear')` triangulates
 * these same points and fills a 200×200 image by interpolating inside each
 * triangle. Here the triangles go to the GPU as they are, with a value at each
 * corner, and the rasteriser does the interpolating — per pixel, at whatever
 * size and angle the view is.
 */
export type FieldMesh = {
  /** Bus positions, in the scene's order, then the four corner anchors. Flat
   *  `[x, y, …]`, world space. */
  xy: Float32Array
  /** Vertex indices into `xy`, three per triangle. */
  triangles: Uint16Array
}

export function buildFieldMesh(scene: Scene): FieldMesh {
  const nBuses = scene.buses.length
  const { minX, maxX, minY, maxY } = scene.bounds
  const pad = (maxX - minX) * PADDING

  const xy = new Float32Array((nBuses + 4) * 2)
  scene.buses.forEach((bus, i) => {
    xy[2 * i] = bus.x
    xy[2 * i + 1] = bus.y
  })
  xy.set(
    [
      minX - pad, minY - pad,
      minX - pad, maxY + pad,
      maxX + pad, minY - pad,
      maxX + pad, maxY + pad,
    ],
    nBuses * 2,
  )
  return { xy, triangles: triangulate(xy) }
}
