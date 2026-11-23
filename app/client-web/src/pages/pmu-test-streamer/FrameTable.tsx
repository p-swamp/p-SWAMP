import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

import type { PmuFrame, PmuHeader } from './usePmuStreamSocket'

/** The column holding `measurement` for `station`, or -1. */
function column(header: PmuHeader, station: string, measurement: string): number {
  return header.station.findIndex((s, i) => s === station && header.measurement[i] === measurement)
}

/** What the table shows, one column each: the layout's distinct measurements and their units. */
function measurements(header: PmuHeader): { name: string; unit: string }[] {
  const seen = new Map<string, string>()
  header.measurement.forEach((name, i) => {
    if (!seen.has(name)) seen.set(name, header.units[i])
  })
  return Array.from(seen, ([name, unit]) => ({ name, unit }))
}

function cell(frame: PmuFrame | null, index: number, unit: string): string {
  const value = frame && index >= 0 ? frame.values[index] : null
  return value === null || value === undefined ? '—' : value.toFixed(unit.startsWith('Hz') ? 4 : 2)
}

/** One frame as a table: a row per station, one column per measurement of the
 *  layout, and the CIM reference the pipeline's enrichment stamped on it. */
export function FrameTable({ header, frame }: { header: PmuHeader; frame: PmuFrame | null }) {
  const stations = Array.from(new Set(header.station))
  const columns = measurements(header)
  return (
    <Table className="font-mono text-xs">
      <TableCaption>CIM reference: {frame?.header.cimReferenceId ?? header.cimReferenceId ?? 'none'}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Station</TableHead>
          {columns.map(({ name, unit }) => (
            <TableHead key={name} className="text-right">
              {name} ({unit})
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {stations.map((station) => (
          <TableRow key={station}>
            <TableCell className="font-medium">{station}</TableCell>
            {columns.map(({ name, unit }) => (
              <TableCell key={name} className="text-right tabular-nums">
                {cell(frame, column(header, station, name), unit)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
