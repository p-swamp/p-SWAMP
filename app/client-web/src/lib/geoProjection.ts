/** Longitude/latitude to a drawing, for the grid maps (the islanding map and the CIM graph page).
 *
 *  Equirectangular, with longitude squeezed by cos(latitude): at Nordic latitudes a degree of
 *  longitude is about half a degree of latitude, and without the correction the map looks stretched
 *  sideways. The bounding box is fitted into `width` x `height`, centred, with the geometry's own
 *  aspect ratio. SVG y grows downward and latitude grows northward, hence the flip. */
export type Bbox = readonly [lonMin: number, latMin: number, lonMax: number, latMax: number]

export function fitProjection(
  bbox: Bbox,
  width: number,
  height: number,
): (lon: number, lat: number) => [number, number] {
  const [lonMin, latMin, lonMax, latMax] = bbox
  const lonScale = Math.cos(((latMin + latMax) / 2) * (Math.PI / 180))
  const w = (lonMax - lonMin) * lonScale
  const h = latMax - latMin
  const scale = Math.min(width / w, height / h)
  const offsetX = (width - w * scale) / 2
  const offsetY = (height - h * scale) / 2
  return (lon, lat) => [
    offsetX + (lon - lonMin) * lonScale * scale,
    height - offsetY - (lat - latMin) * scale,
  ]
}
