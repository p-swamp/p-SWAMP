import type { LiveBuffer, LiveScadaPoint } from './useLiveFeed'

/** The latest scanned value of SCADA point `i`, or null: not scanned yet, or not in the last scan. */
export function scadaValue(buffer: LiveBuffer, i: number): number | null {
  return buffer.scan?.values[i] ?? null
}

/** A flow as it flows into its equipment, the CGMES sign, whatever the measurement says
 *  (`positive_flow_in` false is the other way round). A generator's is then negative. */
export function intoEquipment(point: LiveScadaPoint, value: number): number {
  return point.positive_flow_in === false ? -value : value
}

/** When the latest scan was made, as a reader's clock says it; null before the first. */
export function scanTime(buffer: LiveBuffer): string | null {
  return buffer.scan ? new Date(buffer.scan.t * 1000).toLocaleTimeString() : null
}

/** The system's generation and load, MW, from the latest scan: the generators' active power out of
 *  them and the loads' into them, summed; null where none is scanned. */
export function scadaTotals(buffer: LiveBuffer, points: LiveScadaPoint[]): { generation: number | null; load: number | null } {
  let generation: number | null = null
  let load: number | null = null
  points.forEach((point, i) => {
    const value = scadaValue(buffer, i)
    if (point.quantity !== 'P' || value === null) return
    if (point.kind === 'generator') generation = (generation ?? 0) - intoEquipment(point, value)
    else if (point.kind === 'load') load = (load ?? 0) + intoEquipment(point, value)
  })
  return { generation, load }
}

/** The SCADA points on `equipment` (a line, transformer, machine, load or switch; a voltage level's
 *  node), with their index in the scan. */
export function pointsOn(points: LiveScadaPoint[], test: (point: LiveScadaPoint) => boolean): [LiveScadaPoint, number][] {
  return points.flatMap((point, i) => (test(point) ? [[point, i] as [LiveScadaPoint, number]] : []))
}
