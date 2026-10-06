import { ISLAND_COLORS, PLOT_BACKGROUND } from '../palette'
import {
  type Camera2D,
  type Camera3D,
  focalLength,
  type Projector,
  projector2D,
  projector3D,
  rightOf,
} from './camera'
import type { Scene } from './scene'

/** The Qt grid view's layers. The first four are its "Base layers", on by
 *  default there too; the last two are what its islanding alarm view and its
 *  "Line outages" layer paint over them. */
export type GridLayers = {
  countries: boolean
  lines: boolean
  buses: boolean
  busNames: boolean
  islanding: boolean
  outages: boolean
}

export type GridViewMode = '3d' | '2d'

/** What changes while the page is open. Everything else is the scene. */
export type GridViewData = {
  /** Island index per station. A station not listed is in the main system. */
  islandOf: Map<string, number>
  /** Mean frequency of each island, in Hz, by island index. */
  islandFreq: Map<number, number>
  /** Names of the branches carrying no current: the ones that have tripped,
   *  and the ones a trip has left with nothing to carry. */
  disconnected: Set<string>
  /** False until the detector has reported, so a view can tell "one system"
   *  from "not assessed yet" — the maps above are empty in both cases. */
  assessed: boolean
}

export type Hover = { station: string; x: number; y: number } | null

export type GridRenderer = {
  setData(data: GridViewData): void
  /** Each station's present frequency in Hz, or null when no stream supplies
   *  one. Cheap to call at the stream's rate: it redraws only if a bus moves. */
  setFrequencies(frequencies: Map<string, number> | null): void
  setLayers(layers: GridLayers): void
  setMode(mode: GridViewMode): void
  /** Back to the opening view of the current mode. */
  resetView(): void
  destroy(): void
}

// --- the Qt view's own numbers ---------------------------------------------

/**
 * `GridBasePlot3DLayers.center_camera_position`, plus the widget's default
 * field of view: the same tilt, from the same side, through the same lens.
 *
 * What is not copied is where the camera stands. Qt puts it 40 units from the
 * middle of the buses, which suits a maximised window; this view is a panel
 * whose shape changes when a dock opens beside or beneath it. So the opening
 * view is *fitted*: as close as shows the whole map, and aimed so the map sits
 * in the middle of what is left after the margins below.
 */
const OPENING_VIEW = { elevation: 25, azimuth: -90, fov: 60 }
/** Room kept clear around the fitted map, in pixels. The bottom is deeper
 *  because the legend is laid over that corner; the top, because a bus name is
 *  drawn above its bus and an island running fast rises above where it was
 *  fitted. */
const FIT_MARGIN = { left: 28, right: 28, top: 36, bottom: 58 }

/** `z0` in the Qt layers: the network floats this far above the map, and each
 *  bus stands on a stem down to it. */
const NETWORK_Z = 1
/** `IslandingAlarmView.update_plots`: `node_z = (mean frequency - 50) * 5 + 1`.
 *  An island running fast rises off the map; one running slow sinks. */
const NOMINAL_HZ = 50
const LIFT_PER_HZ = 5

/**
 * Colours as the Qt layers give them. They are *not* what ends up on screen:
 * every GL item there blends additively, so `gray` over the teal background
 * reads as a pale teal and two lines that cross are brighter where they do. The
 * canvas reproduces that with the `lighter` composite rather than by guessing at
 * the blended result.
 */
const COUNTRY_3D = '#404040'
const COUNTRY_2D = '#808080'
const LINE_3D = '#808080'
const LINE_2D = '#ffffff'
const STEM = 'rgba(255, 255, 255, 0.3)'
const NAME_3D = '#ffffff'
const NAME_2D = '#7f7f7f'
const DISCONNECTED = '#ff0000'
/** Qt asks for 2, but of a GL line, which is measured in device pixels. */
const LINE_WIDTH_3D = 1.5
const FONT = '12px "Geist Variable", ui-sans-serif, system-ui, sans-serif'

// --- interaction, after GLViewWidget ----------------------------------------

const ORBIT_DEG_PER_PX = 0.4
const ZOOM_PER_WHEEL_UNIT = 0.0015
const DISTANCE_RANGE: [number, number] = [4, 300]
/** Never below the map: nothing is drawn on its underside. */
const ELEVATION_RANGE: [number, number] = [4, 90]
const HOVER_RADIUS_PX = 14
/** Share of the remaining height difference closed per frame. */
const EASING = 0.14

function clamp(value: number, [low, high]: [number, number]): number {
  return Math.min(high, Math.max(low, value))
}

/**
 * Draws the grid on a canvas and lets the pointer move the camera.
 *
 * Deliberately not a React component. A drag is sixty camera updates a second
 * and an island lifting off the map is an animation, and neither has any
 * business in a render pass -- so this owns the canvas outright, and the
 * component beside it only hands over data when the server sends some. Nothing
 * here redraws unless something it draws has changed.
 */
export function createGridRenderer(
  canvas: HTMLCanvasElement,
  scene: Scene,
  onHover: (hover: Hover) => void,
): GridRenderer {
  const context = canvas.getContext('2d')
  if (!context) throw new Error('2D canvas is not available')
  const ctx = context

  let width = 0
  let height = 0
  let mode: GridViewMode = '3d'
  let layers: GridLayers = {
    countries: true,
    lines: true,
    buses: true,
    busNames: true,
    islanding: true,
    outages: true,
  }
  let data: GridViewData = {
    islandOf: new Map(),
    islandFreq: new Map(),
    disconnected: new Set(),
    assessed: false,
  }

  // Cameras are created on the first draw, once the canvas has a size to fit.
  let camera3D: Camera3D | null = null
  let camera2D: Camera2D | null = null
  // Until the pointer has moved a camera it is still the opening view, and is
  // refitted when the canvas changes size; after that it is the user's.
  let moved3D = false
  let moved2D = false

  const nBuses = scene.buses.length
  const islandOfBus = new Int16Array(nBuses)
  // NaN where the measurement stream has nothing for a station.
  const liveFrequency = new Float32Array(nBuses).fill(NaN)
  const height3D = new Float32Array(nBuses).fill(NETWORK_Z)
  const targetHeight = new Float32Array(nBuses).fill(NETWORK_Z)
  // Where each bus landed on screen in the last frame, for hit-testing a hover.
  const busScreen = new Float32Array(nBuses * 2).fill(NaN)

  // True while the detector reports anything besides the main system.
  let split = false
  let frame = 0
  let hovered = -1
  const point: [number, number] = [0, 0]

  // --- cameras --------------------------------------------------------------

  // What an opening view has to show: the coastlines on the map plane, and the
  // buses above it. Flat `[x, y, z, …]`.
  const fitPoints = new Float32Array(
    [
      ...scene.outlines.flatMap((ring) =>
        Array.from({ length: ring.length / 2 }, (_, i) => [ring[2 * i], ring[2 * i + 1], 0]),
      ),
      ...scene.buses.map((bus) => [bus.x, bus.y, NETWORK_Z]),
    ].flat(),
  )

  /** Screen bounds of everything to be shown, `[left, top, right, bottom]`, or
   *  null if any of it is behind the camera. */
  function projectedBounds(project: Projector): [number, number, number, number] | null {
    const bounds: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity]
    for (let i = 0; i < fitPoints.length; i += 3) {
      if (!project(fitPoints[i], fitPoints[i + 1], fitPoints[i + 2], point)) return null
      bounds[0] = Math.min(bounds[0], point[0])
      bounds[1] = Math.min(bounds[1], point[1])
      bounds[2] = Math.max(bounds[2], point[0])
      bounds[3] = Math.max(bounds[3], point[1])
    }
    return bounds
  }

  function openingCamera3D(): Camera3D {
    const { minX, maxX, minY, maxY } = scene.bounds
    const camera: Camera3D = {
      ...OPENING_VIEW,
      center: [(minX + maxX) / 2, (minY + maxY) / 2, 0],
      distance: DISTANCE_RANGE[1],
    }
    const inner = {
      left: FIT_MARGIN.left,
      top: FIT_MARGIN.top,
      right: width - FIT_MARGIN.right,
      bottom: height - FIT_MARGIN.bottom,
    }
    const fitsFrom = (distance: number): boolean => {
      camera.distance = distance
      const bounds = projectedBounds(projector3D(camera, width, height))
      return (
        bounds !== null &&
        bounds[0] >= inner.left &&
        bounds[1] >= inner.top &&
        bounds[2] <= inner.right &&
        bounds[3] <= inner.bottom
      )
    }
    const closestThatFits = (): number => {
      // The further away, the smaller the map, so "fits" has a single threshold.
      let [near, far] = DISTANCE_RANGE
      for (let i = 0; i < 20; i++) {
        const middle = (near + far) / 2
        if (fitsFrom(middle)) far = middle
        else near = middle
      }
      return far
    }

    // Distance and aim depend on each other — a tilted map does not stay
    // centred as the camera closes in — so alternate between them. A few
    // rounds settle it; it is not worth solving exactly.
    const tilt = Math.sin((camera.elevation * Math.PI) / 180)
    for (let round = 0; round < 6; round++) {
      camera.distance = closestThatFits()
      const bounds = projectedBounds(projector3D(camera, width, height))
      if (!bounds) break
      const perPixel = camera.distance / focalLength(camera, width)
      const offCentreX = (bounds[0] + bounds[2]) / 2 - (inner.left + inner.right) / 2
      const offCentreY = (bounds[1] + bounds[3]) / 2 - (inner.top + inner.bottom) / 2
      // Aiming further east slides the map west on screen; aiming further
      // south slides it up.
      camera.center[0] += offCentreX * perPixel
      camera.center[1] -= (offCentreY * perPixel) / tilt
    }
    camera.distance = closestThatFits()
    return camera
  }

  function openingCamera2D(): Camera2D {
    let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity]
    for (let i = 0; i < fitPoints.length; i += 3) {
      minX = Math.min(minX, fitPoints[i])
      maxX = Math.max(maxX, fitPoints[i])
      minY = Math.min(minY, fitPoints[i + 1])
      maxY = Math.max(maxY, fitPoints[i + 1])
    }
    const innerWidth = width - FIT_MARGIN.left - FIT_MARGIN.right
    const innerHeight = height - FIT_MARGIN.top - FIT_MARGIN.bottom
    const scale = Math.max(
      1,
      Math.min(innerWidth / (maxX - minX), innerHeight / (maxY - minY)),
    )
    // The map's centre goes to the centre of what the margins leave, which is
    // not the centre of the canvas.
    return {
      center: [
        (minX + maxX) / 2 - (FIT_MARGIN.left - FIT_MARGIN.right) / 2 / scale,
        (minY + maxY) / 2 + (FIT_MARGIN.top - FIT_MARGIN.bottom) / 2 / scale,
      ],
      scale,
    }
  }

  // --- drawing --------------------------------------------------------------

  function trace(
    project: Projector,
    xy: Float32Array,
    zAt: (i: number) => number,
  ): void {
    let penDown = false
    for (let i = 0; i < xy.length / 2; i++) {
      if (!project(xy[2 * i], xy[2 * i + 1], zAt(i), point)) {
        penDown = false
        continue
      }
      if (penDown) ctx.lineTo(point[0], point[1])
      else ctx.moveTo(point[0], point[1])
      penDown = true
    }
  }

  function branchColor(from: number, to: number, name: string): string {
    if (layers.outages && data.disconnected.has(name)) return DISCONNECTED
    // Island colours only while there is an island to tell apart. An intact
    // grid is drawn as the Qt base layer draws it; the palette comes in when
    // the grid splits, as it does there when an islanding alarm is opened.
    if (layers.islanding && split) {
      // A branch between two islands takes the later one's colour, which is the
      // order the Qt view paints them in.
      return ISLAND_COLORS[
        Math.max(islandOfBus[from], islandOfBus[to]) % ISLAND_COLORS.length
      ]
    }
    return mode === '3d' ? LINE_3D : LINE_2D
  }

  function draw(): void {
    const dpr = window.devicePixelRatio || 1
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.globalCompositeOperation = 'source-over'
    ctx.fillStyle = PLOT_BACKGROUND
    ctx.fillRect(0, 0, width, height)
    if (width === 0 || height === 0) return

    const flat = mode === '2d'
    camera3D ??= openingCamera3D()
    camera2D ??= openingCamera2D()
    const project = flat
      ? projector2D(camera2D, width, height)
      : projector3D(camera3D, width, height)

    ctx.globalCompositeOperation = 'lighter'
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'

    if (layers.countries) {
      ctx.beginPath()
      for (const ring of scene.outlines) trace(project, ring, () => 0)
      ctx.strokeStyle = flat ? COUNTRY_2D : COUNTRY_3D
      ctx.lineWidth = 1
      ctx.stroke()
    }

    if (layers.buses && !flat) {
      ctx.beginPath()
      scene.buses.forEach((bus, i) => {
        if (!project(bus.x, bus.y, height3D[i], point)) return
        const [x, y] = point
        if (!project(bus.x, bus.y, 0, point)) return
        ctx.moveTo(x, y)
        ctx.lineTo(point[0], point[1])
      })
      ctx.strokeStyle = STEM
      ctx.lineWidth = 1
      ctx.stroke()
    }

    if (layers.lines) {
      for (const branch of scene.branches) {
        const zFrom = height3D[branch.from]
        const zTo = height3D[branch.to]
        const open = layers.outages && data.disconnected.has(branch.name)
        ctx.beginPath()
        trace(project, branch.xy, (i) => zFrom + (zTo - zFrom) * branch.along[i])
        ctx.strokeStyle = branchColor(branch.from, branch.to, branch.name)
        ctx.lineWidth = open ? 2.5 : flat ? 1 : LINE_WIDTH_3D
        ctx.stroke()
      }
    }

    scene.buses.forEach((bus, i) => {
      const visible = project(bus.x, bus.y, height3D[i], point)
      busScreen[2 * i] = visible ? point[0] : NaN
      busScreen[2 * i + 1] = visible ? point[1] : NaN
    })

    if (layers.buses && flat) {
      ctx.fillStyle = '#ffffff'
      for (let i = 0; i < nBuses; i++) {
        if (Number.isNaN(busScreen[2 * i])) continue
        ctx.beginPath()
        ctx.arc(busScreen[2 * i], busScreen[2 * i + 1], 3, 0, 2 * Math.PI)
        ctx.fill()
      }
    }

    if (layers.busNames) {
      ctx.font = FONT
      ctx.fillStyle = flat ? NAME_2D : NAME_3D
      ctx.textAlign = 'left'
      // The 3D text sits on its position, the 2D text hangs below it: the
      // anchors `GLTextItem` and `pg.TextItem(anchor=(0, 0))` give them.
      ctx.textBaseline = flat ? 'top' : 'alphabetic'
      scene.buses.forEach((bus, i) => {
        if (Number.isNaN(busScreen[2 * i])) return
        ctx.fillText(bus.name, busScreen[2 * i] + 2, busScreen[2 * i + 1] + (flat ? 2 : -2))
      })
    }

    if (hovered >= 0 && !Number.isNaN(busScreen[2 * hovered])) {
      ctx.globalCompositeOperation = 'source-over'
      ctx.beginPath()
      ctx.arc(busScreen[2 * hovered], busScreen[2 * hovered + 1], 5, 0, 2 * Math.PI)
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = 1.5
      ctx.stroke()
    }
  }

  /** Move every bus part of the way to its target height. True while any of
   *  them still has somewhere to go. */
  function ease(): boolean {
    let moving = false
    for (let i = 0; i < nBuses; i++) {
      const gap = targetHeight[i] - height3D[i]
      if (Math.abs(gap) < 1e-3) {
        height3D[i] = targetHeight[i]
      } else {
        height3D[i] += gap * EASING
        moving = true
      }
    }
    return moving
  }

  function schedule(): void {
    if (frame) return
    frame = requestAnimationFrame(() => {
      frame = 0
      const moving = mode === '3d' && ease()
      draw()
      if (moving) schedule()
    })
  }

  /**
   * The frequency each island is drawn at: the mean over its stations right
   * now, which is what the Qt alarm view takes per sample. Where the stream has
   * nothing for an island, the mean the detector reported for it stands in --
   * an average over its analysis window, so it trails the stream by seconds.
   */
  function islandFrequencies(): Map<number, number> {
    const sum = new Map<number, number>()
    const count = new Map<number, number>()
    for (let i = 0; i < nBuses; i++) {
      if (Number.isNaN(liveFrequency[i])) continue
      const island = islandOfBus[i]
      sum.set(island, (sum.get(island) ?? 0) + liveFrequency[i])
      count.set(island, (count.get(island) ?? 0) + 1)
    }
    const frequencies = new Map(data.islandFreq)
    sum.forEach((total, island) => frequencies.set(island, total / count.get(island)!))
    return frequencies
  }

  /** Work out where every bus should be. True if any of them has to move. */
  function retarget(): boolean {
    split = false
    scene.buses.forEach((bus, i) => {
      islandOfBus[i] = data.islandOf.get(bus.name) ?? 0
      if (islandOfBus[i] > 0) split = true
    })
    const frequencies = islandFrequencies()
    let moved = false
    for (let i = 0; i < nBuses; i++) {
      const frequency = frequencies.get(islandOfBus[i])
      targetHeight[i] =
        layers.islanding && frequency !== undefined
          ? NETWORK_Z + (frequency - NOMINAL_HZ) * LIFT_PER_HZ
          : NETWORK_Z
      if (Math.abs(targetHeight[i] - height3D[i]) >= 1e-3) moved = true
    }
    return moved
  }

  // --- pointer ---------------------------------------------------------------

  let dragging = false
  let panning = false
  let lastX = 0
  let lastY = 0

  function local(event: PointerEvent | WheelEvent): [number, number] {
    const box = canvas.getBoundingClientRect()
    return [event.clientX - box.left, event.clientY - box.top]
  }

  function onPointerDown(event: PointerEvent): void {
    dragging = true
    // GLViewWidget's bindings: the left button orbits, and the middle button or
    // Ctrl with the left one pans. Shift is accepted too, since a browser
    // claims Ctrl-click for itself on some platforms.
    panning = event.button !== 0 || event.ctrlKey || event.shiftKey || event.metaKey
    ;[lastX, lastY] = local(event)
    canvas.setPointerCapture(event.pointerId)
    canvas.style.cursor = 'grabbing'
    setHover(-1)
  }

  function onPointerMove(event: PointerEvent): void {
    const [x, y] = local(event)
    if (!dragging) {
      hoverAt(x, y)
      return
    }
    const dx = x - lastX
    const dy = y - lastY
    lastX = x
    lastY = y

    if (mode === '2d') {
      if (!camera2D) return
      moved2D = true
      camera2D.center[0] -= dx / camera2D.scale
      camera2D.center[1] += dy / camera2D.scale
    } else {
      if (!camera3D) return
      moved3D = true
      if (panning) {
        // World units per pixel at the point the camera looks at.
        const perPixel = camera3D.distance / focalLength(camera3D, width)
        const [rx, ry] = rightOf(camera3D)
        const az = (camera3D.azimuth * Math.PI) / 180
        // Dragging down pushes the view forward along the ground; the divisor
        // undoes the foreshortening of a tilted map, so it follows the pointer.
        const forward =
          (dy * perPixel) /
          Math.max(0.25, Math.sin((camera3D.elevation * Math.PI) / 180))
        camera3D.center[0] += -rx * dx * perPixel - Math.cos(az) * forward
        camera3D.center[1] += -ry * dx * perPixel - Math.sin(az) * forward
      } else {
        camera3D.azimuth -= dx * ORBIT_DEG_PER_PX
        camera3D.elevation = clamp(
          camera3D.elevation + dy * ORBIT_DEG_PER_PX,
          ELEVATION_RANGE,
        )
      }
    }
    schedule()
  }

  function onPointerUp(event: PointerEvent): void {
    dragging = false
    if (canvas.hasPointerCapture(event.pointerId)) {
      canvas.releasePointerCapture(event.pointerId)
    }
    canvas.style.cursor = 'grab'
  }

  function onWheel(event: WheelEvent): void {
    // Without this the page scrolls under a view that is being zoomed.
    event.preventDefault()
    const factor = Math.exp(event.deltaY * ZOOM_PER_WHEEL_UNIT)
    if (mode === '2d') {
      if (!camera2D) return
      moved2D = true
      // Zoom about the pointer: the spot under it stays under it.
      const [x, y] = local(event)
      const worldX = camera2D.center[0] + (x - width / 2) / camera2D.scale
      const worldY = camera2D.center[1] - (y - height / 2) / camera2D.scale
      camera2D.scale = clamp(camera2D.scale / factor, [2, 2000])
      camera2D.center[0] = worldX - (x - width / 2) / camera2D.scale
      camera2D.center[1] = worldY + (y - height / 2) / camera2D.scale
    } else {
      if (!camera3D) return
      moved3D = true
      camera3D.distance = clamp(camera3D.distance * factor, DISTANCE_RANGE)
    }
    schedule()
  }

  function setHover(index: number): void {
    if (index === hovered) return
    hovered = index
    onHover(
      index < 0
        ? null
        : {
            station: scene.buses[index].name,
            x: busScreen[2 * index],
            y: busScreen[2 * index + 1],
          },
    )
    schedule()
  }

  function hoverAt(x: number, y: number): void {
    let nearest = -1
    let best = HOVER_RADIUS_PX
    for (let i = 0; i < nBuses; i++) {
      const distance = Math.hypot(busScreen[2 * i] - x, busScreen[2 * i + 1] - y)
      if (distance < best) {
        best = distance
        nearest = i
      }
    }
    setHover(nearest)
  }

  function onPointerLeave(): void {
    if (!dragging) setHover(-1)
  }

  function resetView(): void {
    if (mode === '2d') {
      camera2D = null
      moved2D = false
    } else {
      camera3D = null
      moved3D = false
    }
    schedule()
  }

  // --- size -------------------------------------------------------------------

  const observer = new ResizeObserver(() => {
    const box = canvas.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    width = box.width
    height = box.height
    canvas.width = Math.round(width * dpr)
    canvas.height = Math.round(height * dpr)
    if (!moved3D) camera3D = null
    if (!moved2D) camera2D = null
    // Resizing a canvas clears it, so draw now rather than on the next frame:
    // a frame of blank canvas during a window resize reads as a flicker.
    cancelAnimationFrame(frame)
    frame = 0
    draw()
  })
  observer.observe(canvas)

  canvas.style.cursor = 'grab'
  // The browser must not turn a drag into a scroll or a pinch into a page zoom.
  canvas.style.touchAction = 'none'
  canvas.addEventListener('pointerdown', onPointerDown)
  canvas.addEventListener('pointermove', onPointerMove)
  canvas.addEventListener('pointerup', onPointerUp)
  canvas.addEventListener('pointercancel', onPointerUp)
  canvas.addEventListener('pointerleave', onPointerLeave)
  canvas.addEventListener('dblclick', resetView)
  // Not passive: the handler has to be able to cancel the scroll.
  canvas.addEventListener('wheel', onWheel, { passive: false })

  return {
    setData(next) {
      data = next
      retarget()
      schedule()
    },
    setFrequencies(next) {
      scene.buses.forEach((bus, i) => {
        liveFrequency[i] = next?.get(bus.name) ?? NaN
      })
      // The stream ticks ten times a second and usually moves nothing visible;
      // a redraw is only owed when a bus has somewhere to go.
      if (retarget() && mode === '3d') schedule()
    },
    setLayers(next) {
      layers = next
      retarget()
      schedule()
    },
    setMode(next) {
      mode = next
      // Heights are a 3D matter; arriving back in 3D they are already where
      // they belong rather than animating up from wherever they were left.
      height3D.set(targetHeight)
      schedule()
    },
    resetView,
    destroy() {
      observer.disconnect()
      cancelAnimationFrame(frame)
      canvas.removeEventListener('pointerdown', onPointerDown)
      canvas.removeEventListener('pointermove', onPointerMove)
      canvas.removeEventListener('pointerup', onPointerUp)
      canvas.removeEventListener('pointercancel', onPointerUp)
      canvas.removeEventListener('pointerleave', onPointerLeave)
      canvas.removeEventListener('dblclick', resetView)
      canvas.removeEventListener('wheel', onWheel)
    },
  }
}
