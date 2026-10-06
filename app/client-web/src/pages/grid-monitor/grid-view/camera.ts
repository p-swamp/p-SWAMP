/**
 * The grid view's two projections, as plain functions over plain numbers.
 *
 * The Qt grid view is a pyqtgraph `GLViewWidget`, but what it draws is only
 * polylines and text -- no surfaces, nothing that hides anything else -- so it
 * needs neither a depth buffer nor WebGL. Projecting the points ourselves and
 * stroking them on a 2D canvas gives the same picture with no rendering library,
 * and the camera below takes the very parameters the Qt view sets, so "the same
 * view" is a matter of copying four numbers.
 *
 * World space is the Qt view's: x is longitude, y is latitude times the
 * diagram's aspect ratio, z is height above the map.
 */

export type Vec3 = [number, number, number]

/** `GLViewWidget.opts`: an orbit camera looking at `center`. */
export type Camera3D = {
  center: Vec3
  distance: number
  /** Degrees above the map plane; 90 looks straight down. */
  elevation: number
  /** Degrees around the vertical; -90 looks north, with east to the right. */
  azimuth: number
  /** Horizontal field of view in degrees, as pyqtgraph defines it. */
  fov: number
}

/** A flat, north-up view: what the Qt 2D grid plot shows. */
export type Camera2D = {
  center: [number, number]
  /** Pixels per world unit. */
  scale: number
}

/** Writes the screen position of a world point into `out`; false if the point
 *  is behind the viewer and must not be drawn. */
export type Projector = (
  x: number,
  y: number,
  z: number,
  out: [number, number],
) => boolean

const RAD = Math.PI / 180

/** Pixels per world unit at the camera's focus, which is what a drag has to be
 *  scaled by for the scene to follow the pointer. */
export function focalLength(camera: Camera3D, width: number): number {
  return width / 2 / Math.tan((camera.fov * RAD) / 2)
}

/** The unit vector pointing right on screen. Always horizontal, and defined
 *  from the azimuth alone so that it survives looking straight down. */
export function rightOf(camera: Camera3D): [number, number] {
  const az = camera.azimuth * RAD
  return [-Math.sin(az), Math.cos(az)]
}

export function projector3D(
  camera: Camera3D,
  width: number,
  height: number,
): Projector {
  const el = camera.elevation * RAD
  const az = camera.azimuth * RAD
  // From the camera towards the centre.
  const fx = -Math.cos(el) * Math.cos(az)
  const fy = -Math.cos(el) * Math.sin(az)
  const fz = -Math.sin(el)
  const [rx, ry] = rightOf(camera)
  // right x forward: the direction that is up on screen.
  const ux = ry * fz
  const uy = -rx * fz
  const uz = rx * fy - ry * fx
  // Camera position.
  const cx = camera.center[0] - fx * camera.distance
  const cy = camera.center[1] - fy * camera.distance
  const cz = camera.center[2] - fz * camera.distance
  const focal = focalLength(camera, width)
  const near = camera.distance * 0.001

  return (x, y, z, out) => {
    const dx = x - cx
    const dy = y - cy
    const dz = z - cz
    const depth = dx * fx + dy * fy + dz * fz
    if (depth <= near) return false
    out[0] = width / 2 + ((dx * rx + dy * ry) / depth) * focal
    out[1] = height / 2 - ((dx * ux + dy * uy + dz * uz) / depth) * focal
    return true
  }
}

export function projector2D(
  camera: Camera2D,
  width: number,
  height: number,
): Projector {
  return (x, y, _z, out) => {
    out[0] = width / 2 + (x - camera.center[0]) * camera.scale
    out[1] = height / 2 - (y - camera.center[1]) * camera.scale
    return true
  }
}
