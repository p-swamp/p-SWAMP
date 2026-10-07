import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  CanvasTexture,
  Color,
  DoubleSide,
  DynamicDrawUsage,
  InstancedInterleavedBuffer,
  InterleavedBufferAttribute,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  NormalBlending,
  OrthographicCamera,
  PerspectiveCamera,
  Points,
  PointsMaterial,
  Scene as ThreeScene,
  ShaderMaterial,
  WebGLRenderer,
} from 'three'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js'

import { PLOT_BACKGROUND } from '../palette'
import type { Camera2D, Camera3D } from './camera'
import type { FieldMesh } from './field'
import type { Scene } from './scene'

/**
 * How one branch is to be drawn.
 *
 * `plain` is a branch in the view's base colour. The other two carry a meaning
 * — an island's colour, or the red of a branch with no current — and are kept
 * apart from the plain ones because they blend differently over a field, and a
 * dead branch is drawn wider.
 */
export type BranchStyle = { color: string; group: 'plain' | 'island' | 'dead' }

/** Everything about one frame that the picture depends on. */
export type Frame = {
  flat: boolean
  camera3D: Camera3D
  camera2D: Camera2D
  width: number
  height: number
  show: { countries: boolean; lines: boolean; buses: boolean }
  /** Height of each bus above the map. */
  heights: Float32Array
  /** Height of the field's corner anchors. */
  anchorHeight: number
  /** The field at each bus, as a share of its limit: -1 and 1 are the ends of
   *  the colour scale, 0 is "nothing to show". Null when no field is on. */
  levels: Float32Array | null
}

export type GlPainter = {
  canvas: HTMLCanvasElement
  resize(width: number, height: number, pixelRatio: number): void
  /**
   * Sort the branches into their groups and colour them. Called when what a
   * branch *is* changes — an island forms, a line trips, a layer is switched —
   * not once a frame: it refills the line buffers.
   *
   * `additive` is whether the meaning-carrying groups glow like the plain ones
   * or are painted. Over a field they have to be painted: red added to blue
   * reads as magenta.
   */
  setBranchStyles(styles: BranchStyle[], flat: boolean, additive: boolean): void
  render(frame: Frame): void
  dispose(): void
}

// The Qt layers' colours and widths. See renderer.ts for where each comes from.
const COUNTRY_3D = '#404040'
const COUNTRY_2D = '#808080'
const STEM_OPACITY = 0.3
/** Qt asks for 2, but of a GL line, which is measured in device pixels. */
const LINE_WIDTH_3D = 1.5
const LINE_WIDTH_2D = 1
const DEAD_LINE_WIDTH = 2.5
const BUS_DOT_PX = 6

const RAD = Math.PI / 180

/** A round, white dot, for the 2D bus markers: GL points are square. */
function dotTexture(): CanvasTexture {
  const size = 32
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (ctx) {
    ctx.fillStyle = '#ffffff'
    ctx.beginPath()
    ctx.arc(size / 2, size / 2, size / 2 - 1, 0, 2 * Math.PI)
    ctx.fill()
  }
  return new CanvasTexture(canvas)
}

/**
 * One set of thick lines: a fixed pool of segments, of which the first few are
 * in use. Which branches it holds changes now and then; where their points are
 * changes every frame an island is rising.
 */
function branchGroup(scene: Scene, totalSegments: number) {
  const positions = new Float32Array(totalSegments * 6)
  const colors = new Float32Array(totalSegments * 6)
  // What `LineSegmentsGeometry.setPositions` and `setColors` build, built here
  // so the two buffers can be written to and flagged afterwards: one start and
  // one end per segment, each segment an instance of the same quad.
  const positionBuffer = new InstancedInterleavedBuffer(positions, 6, 1).setUsage(DynamicDrawUsage)
  const colorBuffer = new InstancedInterleavedBuffer(colors, 6, 1)
  const geometry = new LineSegmentsGeometry()
  geometry.setAttribute('instanceStart', new InterleavedBufferAttribute(positionBuffer, 3, 0))
  geometry.setAttribute('instanceEnd', new InterleavedBufferAttribute(positionBuffer, 3, 3))
  geometry.setAttribute('instanceColorStart', new InterleavedBufferAttribute(colorBuffer, 3, 0))
  geometry.setAttribute('instanceColorEnd', new InterleavedBufferAttribute(colorBuffer, 3, 3))
  geometry.instanceCount = 0
  const material = new LineMaterial({
    vertexColors: true,
    transparent: true,
    depthTest: false,
    depthWrite: false,
  })
  const object = new LineSegments2(geometry, material)
  // Its bounds are worked out once, from an empty pool; never cull by them.
  object.frustumCulled = false
  let members: number[] = []

  return {
    object,
    material,
    fill(next: number[], colorOf: (branch: number) => Color): void {
      members = next
      let segment = 0
      for (const index of members) {
        const color = colorOf(index)
        const count = scene.branches[index].xy.length / 2 - 1
        for (let k = 0; k < count; k++, segment++) {
          for (let end = 0; end < 2; end++) color.toArray(colors, segment * 6 + end * 3)
        }
      }
      geometry.instanceCount = segment
      colorBuffer.needsUpdate = true
    },
    /** Put every point where its branch's two buses now are. */
    place(heights: Float32Array): void {
      let segment = 0
      for (const index of members) {
        const { xy, along, from, to } = scene.branches[index]
        const zFrom = heights[from]
        const rise = heights[to] - zFrom
        for (let k = 0; k < xy.length / 2 - 1; k++, segment++) {
          positions.set(
            [
              xy[2 * k], xy[2 * k + 1], zFrom + rise * along[k],
              xy[2 * k + 2], xy[2 * k + 3], zFrom + rise * along[k + 1],
            ],
            segment * 6,
          )
        }
      }
      positionBuffer.needsUpdate = true
    },
    dispose(): void {
      geometry.dispose()
      material.dispose()
    },
  }
}

/**
 * The grid, drawn with WebGL through three.js — as the Qt grid view draws it
 * with OpenGL through pyqtgraph.
 *
 * Nothing here decides anything. It is handed a frame — where the camera is,
 * how high each bus rides, what colour each branch is — and puts it on screen;
 * what those are is the renderer's business. The one piece of Qt carried over
 * wholesale is the blending: its GL items add their colour to what is under
 * them, depth test off, so nothing hides anything and crossing lines brighten.
 * The 2D plot there is an ordinary painter, and is drawn as one here.
 *
 * Text is not drawn here: GL has none. The renderer lays bus names over this
 * canvas on a second, 2D one, much as Qt paints its labels over the GL scene.
 *
 * @throws if the browser cannot give the canvas a WebGL context.
 */
export function createGlPainter(scene: Scene, field: FieldMesh): GlPainter {
  // preserveDrawingBuffer: the picture has to still be there when a test, or a
  // "save image", reads the canvas after the frame that drew it.
  const renderer = new WebGLRenderer({ antialias: true, preserveDrawingBuffer: true })
  renderer.setClearColor(new Color(PLOT_BACKGROUND), 1)
  const canvas = renderer.domElement

  const world = new ThreeScene()
  const perspective = new PerspectiveCamera()
  const orthographic = new OrthographicCamera()
  const nBuses = scene.buses.length

  // Every material is flagged transparent, not because it all is, but because
  // that is the list three.js draws strictly in `renderOrder` — and with the
  // depth test off, order is the only thing deciding what is over what.
  const layered = <T extends { renderOrder: number; frustumCulled: boolean }>(
    object: T,
    order: number,
  ): T => {
    object.renderOrder = order
    object.frustumCulled = false
    return object
  }

  // --- the field: a mesh over the buses, coloured in the fragment shader ------

  const nVertices = field.xy.length / 2
  const surfacePositions = new Float32Array(nVertices * 3)
  const surfaceLevels = new Float32Array(nVertices)
  const surfaceGeometry = new BufferGeometry()
  surfaceGeometry.setAttribute(
    'position',
    new BufferAttribute(surfacePositions, 3).setUsage(DynamicDrawUsage),
  )
  surfaceGeometry.setAttribute(
    'level',
    new BufferAttribute(surfaceLevels, 1).setUsage(DynamicDrawUsage),
  )
  surfaceGeometry.setIndex(new BufferAttribute(field.triangles, 1))
  const surfaceMaterial = new ShaderMaterial({
    // The Qt colour map runs red → background → blue. Here that is red or blue
    // with the level as opacity, which over the plot background is the same
    // picture. The level is interpolated across each triangle by the rasteriser
    // and clamped per pixel: exactly `griddata(method='linear')` and a colour
    // bar's limits, without an image in between.
    vertexShader: `
      attribute float level;
      varying float vLevel;
      void main() {
        vLevel = level;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: `
      varying float vLevel;
      void main() {
        float level = clamp(vLevel, -1.0, 1.0);
        gl_FragColor = vec4(level < 0.0 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 0.0, 1.0), abs(level));
      }`,
    transparent: true,
    depthTest: false,
    depthWrite: false,
    side: DoubleSide,
    blending: NormalBlending,
  })
  const surface = layered(new Mesh(surfaceGeometry, surfaceMaterial), 0)
  world.add(surface)

  // --- countries: thin lines on the map plane ---------------------------------

  const outlinePoints: number[] = []
  for (const ring of scene.outlines) {
    for (let i = 0; i + 1 < ring.length / 2; i++) {
      outlinePoints.push(ring[2 * i], ring[2 * i + 1], 0, ring[2 * i + 2], ring[2 * i + 3], 0)
    }
  }
  const outlineGeometry = new BufferGeometry()
  outlineGeometry.setAttribute(
    'position',
    new BufferAttribute(new Float32Array(outlinePoints), 3),
  )
  const outlineMaterial = new LineBasicMaterial({ transparent: true, depthTest: false })
  const outlines = layered(new LineSegments(outlineGeometry, outlineMaterial), 1)
  world.add(outlines)

  // --- stems: each bus stands on one, down to the map --------------------------

  const stemPositions = new Float32Array(nBuses * 6)
  scene.buses.forEach((bus, i) => {
    stemPositions.set([bus.x, bus.y, 0, bus.x, bus.y, 0], i * 6)
  })
  const stemGeometry = new BufferGeometry()
  stemGeometry.setAttribute(
    'position',
    new BufferAttribute(stemPositions, 3).setUsage(DynamicDrawUsage),
  )
  const stemMaterial = new LineBasicMaterial({
    color: '#ffffff',
    opacity: STEM_OPACITY,
    transparent: true,
    depthTest: false,
    blending: AdditiveBlending,
  })
  const stems = layered(new LineSegments(stemGeometry, stemMaterial), 2)
  world.add(stems)

  // --- branches: thick lines, in three groups ----------------------------------

  const totalSegments = scene.branches.reduce(
    (sum, branch) => sum + branch.xy.length / 2 - 1,
    0,
  )
  const plain = branchGroup(scene, totalSegments)
  const island = branchGroup(scene, totalSegments)
  const dead = branchGroup(scene, totalSegments)
  world.add(layered(plain.object, 3), layered(island.object, 4), layered(dead.object, 5))

  // --- bus markers, for the 2D view ---------------------------------------------

  const dotGeometry = new BufferGeometry()
  dotGeometry.setAttribute(
    'position',
    new BufferAttribute(
      new Float32Array(scene.buses.flatMap((bus) => [bus.x, bus.y, 0])),
      3,
    ),
  )
  const dotMap = dotTexture()
  const dotMaterial = new PointsMaterial({
    color: '#ffffff',
    size: BUS_DOT_PX,
    sizeAttenuation: false,
    map: dotMap,
    transparent: true,
    depthTest: false,
  })
  const dots = layered(new Points(dotGeometry, dotMaterial), 6)
  world.add(dots)

  const disposables: { dispose(): void }[] = [
    surfaceGeometry,
    surfaceMaterial,
    outlineGeometry,
    outlineMaterial,
    stemGeometry,
    stemMaterial,
    plain,
    island,
    dead,
    dotGeometry,
    dotMaterial,
    dotMap,
  ]

  // --- cameras ------------------------------------------------------------------

  /** Stand the GL camera where `camera.ts` says the view is from, so that what
   *  is drawn here and what is projected there for labels and hover agree. */
  function aimPerspective(view: Camera3D, width: number, height: number) {
    const el = view.elevation * RAD
    const az = view.azimuth * RAD
    const forward = [-Math.cos(el) * Math.cos(az), -Math.cos(el) * Math.sin(az), -Math.sin(el)]
    const right = [-Math.sin(az), Math.cos(az)]
    // pyqtgraph's field of view is the horizontal one; three.js wants vertical.
    perspective.fov =
      (2 * Math.atan((Math.tan((view.fov * RAD) / 2) * height) / width)) / RAD
    perspective.aspect = width / height
    perspective.near = view.distance * 0.001
    perspective.far = view.distance * 1000
    perspective.position.set(
      view.center[0] - forward[0] * view.distance,
      view.center[1] - forward[1] * view.distance,
      view.center[2] - forward[2] * view.distance,
    )
    // right × forward: which way is up on screen. Given outright rather than
    // as "z is up", which stops meaning anything when looking straight down.
    perspective.up.set(
      right[1] * forward[2],
      -right[0] * forward[2],
      right[0] * forward[1] - right[1] * forward[0],
    )
    perspective.lookAt(view.center[0], view.center[1], view.center[2])
    perspective.updateProjectionMatrix()
    return perspective
  }

  function aimOrthographic(view: Camera2D, width: number, height: number) {
    orthographic.left = -width / 2 / view.scale
    orthographic.right = width / 2 / view.scale
    orthographic.top = height / 2 / view.scale
    orthographic.bottom = -height / 2 / view.scale
    orthographic.near = 1
    orthographic.far = 2000
    orthographic.position.set(view.center[0], view.center[1], 1000)
    orthographic.up.set(0, 1, 0)
    orthographic.lookAt(view.center[0], view.center[1], 0)
    orthographic.updateProjectionMatrix()
    return orthographic
  }

  return {
    canvas,
    resize(width, height, pixelRatio) {
      renderer.setPixelRatio(pixelRatio)
      // false: the canvas is sized by the page's CSS, not by three.js.
      renderer.setSize(width, height, false)
    },
    setBranchStyles(styles, flat, additive) {
      const members = { plain: [] as number[], island: [] as number[], dead: [] as number[] }
      styles.forEach((style, index) => members[style.group].push(index))
      // Parsed as sRGB and held linear, which is what a vertex colour has to be.
      const parsed = new Map<string, Color>()
      const colorOf = (index: number): Color => {
        const css = styles[index].color
        if (!parsed.has(css)) parsed.set(css, new Color(css))
        return parsed.get(css)!
      }
      plain.fill(members.plain, colorOf)
      island.fill(members.island, colorOf)
      dead.fill(members.dead, colorOf)

      const glow = flat ? NormalBlending : AdditiveBlending
      plain.material.blending = glow
      island.material.blending = additive ? glow : NormalBlending
      dead.material.blending = additive ? glow : NormalBlending
      plain.material.linewidth = flat ? LINE_WIDTH_2D : LINE_WIDTH_3D
      island.material.linewidth = flat ? LINE_WIDTH_2D : LINE_WIDTH_3D
      dead.material.linewidth = DEAD_LINE_WIDTH
    },
    render(frame) {
      const { flat, heights } = frame

      surface.visible = frame.levels !== null
      if (frame.levels) {
        for (let v = 0; v < nVertices; v++) {
          const isBus = v < nBuses
          surfacePositions.set(
            [field.xy[2 * v], field.xy[2 * v + 1], isBus ? heights[v] : frame.anchorHeight],
            v * 3,
          )
          // The corner anchors carry no deviation, by definition; a bus the
          // stream has nothing for is treated the same.
          const level = isBus ? frame.levels[v] : 0
          surfaceLevels[v] = Number.isFinite(level) ? level : 0
        }
        surfaceGeometry.attributes.position.needsUpdate = true
        surfaceGeometry.attributes.level.needsUpdate = true
      }

      outlines.visible = frame.show.countries
      outlineMaterial.color.set(flat ? COUNTRY_2D : COUNTRY_3D)
      outlineMaterial.blending = flat ? NormalBlending : AdditiveBlending

      stems.visible = frame.show.buses && !flat
      if (stems.visible) {
        for (let i = 0; i < nBuses; i++) stemPositions[i * 6 + 2] = heights[i]
        stemGeometry.attributes.position.needsUpdate = true
      }

      for (const group of [plain, island, dead]) {
        group.object.visible = frame.show.lines
        if (frame.show.lines) group.place(heights)
      }

      dots.visible = frame.show.buses && flat

      renderer.render(
        world,
        flat
          ? aimOrthographic(frame.camera2D, frame.width, frame.height)
          : aimPerspective(frame.camera3D, frame.width, frame.height),
      )
    },
    dispose() {
      disposables.forEach((item) => item.dispose())
      renderer.dispose()
      // The browser keeps only so many GL contexts alive; give this one back
      // now rather than whenever the canvas is collected.
      renderer.forceContextLoss()
    },
  }
}
