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

function cell(frame: PmuFrame | null, index: number, digits: number): string {
  const value = frame && index >= 0 ? frame.values[index] : null
  return value === null || value === undefined ? '—' : value.toFixed(digits)
}

/** One frame as a table: a row per station, one column per measurement, and
 *  the CIM reference the gateway stamped on its layout. */
export function FrameTable({ header, frame }: { header: PmuHeader; frame: PmuFrame | null }) {
  const stations = Array.from(new Set(header.station))
  return (
    <Table className="font-mono text-xs">
      <TableCaption>CIM reference: {frame?.header.cimReferenceId ?? header.cimReferenceId ?? 'none'}</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Station</TableHead>
          <TableHead className="text-right">V (kV)</TableHead>
          <TableHead className="text-right">angle (deg)</TableHead>
          <TableHead className="text-right">f (Hz)</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {stations.map((station) => (
          <TableRow key={station}>
            <TableCell className="font-medium">{station}</TableCell>
            <TableCell className="text-right tabular-nums">{cell(frame, column(header, station, 'V_Magnitude'), 2)}</TableCell>
            <TableCell className="text-right tabular-nums">{cell(frame, column(header, station, 'V_Angle'), 2)}</TableCell>
            <TableCell className="text-right tabular-nums">{cell(frame, column(header, station, 'f'), 4)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
