/**
 * Delaunay triangulation of a small point set (Bowyer–Watson).
 *
 * The Qt heat map interpolates between the buses with `scipy.griddata(...,
 * method='linear')`, which is exactly this: triangulate the points, then
 * interpolate linearly inside each triangle. A few dozen points do not justify a
 * geometry library, and the textbook algorithm is about forty lines.
 *
 * Quadratic in the number of points, which is fine for the forty-eight it gets.
 * Points sharing a position must not be passed in: they would have no triangle
 * between them.
 *
 * @param xy Flat `[x, y, x, y, …]`.
 * @returns Flat triangle vertex indices, three per triangle.
 */
export function triangulate(xy: ArrayLike<number>): Uint16Array {
  const n = xy.length / 2
  if (n < 3) return new Uint16Array(0)

  let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity]
  for (let i = 0; i < n; i++) {
    minX = Math.min(minX, xy[2 * i])
    maxX = Math.max(maxX, xy[2 * i])
    minY = Math.min(minY, xy[2 * i + 1])
    maxY = Math.max(maxY, xy[2 * i + 1])
  }

  // The points, plus three more forming a triangle that contains them all with
  // room to spare. Every real triangle is carved out of that one.
  const span = Math.max(maxX - minX, maxY - minY) || 1
  const midX = (minX + maxX) / 2
  const midY = (minY + maxY) / 2
  const px = new Float64Array(n + 3)
  const py = new Float64Array(n + 3)
  for (let i = 0; i < n; i++) {
    px[i] = xy[2 * i]
    py[i] = xy[2 * i + 1]
  }
  px.set([midX - 20 * span, midX, midX + 20 * span], n)
  py.set([midY - span, midY + 20 * span, midY - span], n)

  /** Whether point `p` is inside the circle through a triangle's corners. */
  const inCircumcircle = (a: number, b: number, c: number, p: number): boolean => {
    const ax = px[a] - px[p]
    const ay = py[a] - py[p]
    const bx = px[b] - px[p]
    const by = py[b] - py[p]
    const cx = px[c] - px[p]
    const cy = py[c] - py[p]
    const det =
      (ax * ax + ay * ay) * (bx * cy - cx * by) -
      (bx * bx + by * by) * (ax * cy - cx * ay) +
      (cx * cx + cy * cy) * (ax * by - bx * ay)
    // The sign of `det` depends on which way round the triangle is listed.
    const anticlockwise =
      (px[b] - px[a]) * (py[c] - py[a]) - (px[c] - px[a]) * (py[b] - py[a]) > 0
    return anticlockwise ? det > 0 : det < 0
  }

  let triangles: [number, number, number][] = [[n, n + 1, n + 2]]
  for (let p = 0; p < n; p++) {
    // Every triangle whose circle the new point falls in is no longer Delaunay.
    // Together they form a hole around the point …
    const kept: [number, number, number][] = []
    const edges = new Map<string, [number, number]>()
    for (const triangle of triangles) {
      if (!inCircumcircle(triangle[0], triangle[1], triangle[2], p)) {
        kept.push(triangle)
        continue
      }
      for (let k = 0; k < 3; k++) {
        const a = triangle[k]
        const b = triangle[(k + 1) % 3]
        const key = a < b ? `${a},${b}` : `${b},${a}`
        // An edge two of the removed triangles shared is inside the hole; only
        // the ones seen once are its boundary.
        if (edges.has(key)) edges.delete(key)
        else edges.set(key, [a, b])
      }
    }
    // … which is re-filled by joining each edge of its boundary to the point.
    for (const [a, b] of edges.values()) kept.push([a, b, p])
    triangles = kept
  }

  const real = triangles.filter((t) => t[0] < n && t[1] < n && t[2] < n)
  return Uint16Array.from(real.flat())
}
