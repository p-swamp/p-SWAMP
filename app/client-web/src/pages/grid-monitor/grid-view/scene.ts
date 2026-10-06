import type { Wire } from '@/api/wire'

/** The static topology and diagram, straight from the contract
 *  (`GET /api/grid/model`). */
export type GridModel = Wire['GridModel']

/** A branch as the view draws it: where it runs, and which buses it hangs from. */
export type SceneBranch = {
  name: string
  from: number
  to: number
  /** Flat `[x, y, x, y, …]` in world space. */
  xy: Float32Array
  /** For each point, how far along the route it is, 0 at `from` to 1 at `to`.
   *  A bus's height is spread along the branch by this, so a line between two
   *  islands slopes from one to the other -- `LineLayer.build_z_map` in Qt. */
  along: Float32Array
}

/**
 * Everything the grid view draws that does not change while the page is open,
 * converted once into world space and typed arrays.
 *
 * World space is the Qt view's: x is longitude and y is latitude times the
 * diagram's aspect ratio, which is how it keeps Norway from looking squashed.
 */
export type Scene = {
  outlines: Float32Array[]
  buses: { name: string; x: number; y: number }[]
  busIndex: Map<string, number>
  branches: SceneBranch[]
  bounds: { minX: number; maxX: number; minY: number; maxY: number }
}

function flatten(points: [number, number][], aspect: number): Float32Array {
  const xy = new Float32Array(points.length * 2)
  points.forEach(([lon, lat], i) => {
    xy[2 * i] = lon
    xy[2 * i + 1] = lat * aspect
  })
  return xy
}

function fractionAlong(xy: Float32Array): Float32Array {
  const n = xy.length / 2
  const along = new Float32Array(n)
  for (let i = 1; i < n; i++) {
    along[i] =
      along[i - 1] +
      Math.hypot(xy[2 * i] - xy[2 * i - 2], xy[2 * i + 1] - xy[2 * i - 1])
  }
  const total = along[n - 1]
  if (total > 0) for (let i = 0; i < n; i++) along[i] /= total
  return along
}

/** Null when the server sent no diagram: there is then nothing to draw a grid
 *  view *from*, and the caller says so rather than drawing a guess. */
export function buildScene(model: GridModel): Scene | null {
  const diagram = model.diagram
  if (!diagram) return null
  const aspect = diagram.aspect_ratio

  const buses = Object.entries(diagram.buses).map(([name, [lon, lat]]) => ({
    name,
    x: lon,
    y: lat * aspect,
  }))
  const busIndex = new Map(buses.map((bus, i) => [bus.name, i]))

  const branches: SceneBranch[] = []
  for (const branch of model.branches) {
    const path = diagram.branches[branch.name]
    const from = busIndex.get(branch.from_bus)
    const to = busIndex.get(branch.to_bus)
    if (!path || path.length < 2 || from === undefined || to === undefined) continue
    const xy = flatten(path, aspect)
    branches.push({ name: branch.name, from, to, xy, along: fractionAlong(xy) })
  }

  const xs = buses.map((bus) => bus.x)
  const ys = buses.map((bus) => bus.y)
  return {
    outlines: diagram.outlines.map((ring) => flatten(ring, aspect)),
    buses,
    busIndex,
    branches,
    bounds: {
      minX: Math.min(...xs),
      maxX: Math.max(...xs),
      minY: Math.min(...ys),
      maxY: Math.max(...ys),
    },
  }
}
