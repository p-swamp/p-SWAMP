import { useMemo, useState } from 'react'
import { ArrowDownIcon, ArrowUpIcon, ChevronsUpDownIcon } from 'lucide-react'

import { TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

import type { PmuFrame, PmuHeader } from './usePmuStreamSocket'

/** The sort key of the station column; the others are positions in `layout.columns`. */
const STATION = -1

const collator = new Intl.Collator(undefined, { numeric: true })

interface Sort {
  key: number
  descending: boolean
}

/** Clicking a column sorts ascending, then descending, then back to the layout's order. */
function nextSort(current: Sort | null, key: number): Sort | null {
  if (current?.key !== key) return { key, descending: false }
  return current.descending ? null : { key, descending: true }
}

/** What the table shows, from the layout alone: its stations, its distinct measurements
 *  with their units (one column each), and where each station's value of each is. */
function layoutOf(header: PmuHeader) {
  const stations = Array.from(new Set(header.station))
  const units = new Map<string, string>()
  const index = new Map<string, number>()
  header.measurement.forEach((name, i) => {
    if (!units.has(name)) units.set(name, header.units[i])
    const key = `${header.station[i]}\u0000${name}`
    if (!index.has(key)) index.set(key, i)
  })
  const columns = Array.from(units, ([name, unit]) => ({ name, unit }))
  return { stations, columns, index }
}

function format(value: number | null, unit: string): string {
  return value === null ? '—' : value.toFixed(unit.startsWith('Hz') ? 4 : 2)
}

/** A header cell that sorts by its column. `sticky` pins it to the top of the screen;
 *  it only does so while no ancestor clips overflow, hence the plain table below. */
function SortableHead({
  label,
  sort,
  column,
  onSort,
  right = true,
}: {
  label: string
  sort: Sort | null
  column: number
  onSort: (column: number) => void
  right?: boolean
}) {
  const active = sort?.key === column ? sort : null
  const Icon = active === null ? ChevronsUpDownIcon : active.descending ? ArrowDownIcon : ArrowUpIcon
  return (
    <TableHead
      aria-sort={active === null ? 'none' : active.descending ? 'descending' : 'ascending'}
      className={cn(
        'sticky top-0 z-10 bg-card p-0 shadow-[inset_0_-1px_0_0_var(--border)]',
        right && 'text-right',
      )}
    >
      <button
        type="button"
        onClick={() => onSort(column)}
        className={cn(
          'flex h-full w-full items-center gap-1 px-2 py-2.5 whitespace-nowrap hover:bg-muted/50',
          right && 'justify-end',
        )}
      >
        {label}
        <Icon className={cn('size-3', active === null && 'text-muted-foreground/60')} aria-hidden="true" />
      </button>
    </TableHead>
  )
}

/** One frame as a table: a row per station, one column per measurement of the
 *  layout, and the CIM reference the pipeline's enrichment stamped on it. Click a
 *  column to sort by it; the header stays at the top of the screen while the
 *  rows scroll. The values follow the frame, so a column sorted by a live value
 *  reorders as it changes. */
export function FrameTable({ header, frame }: { header: PmuHeader; frame: PmuFrame | null }) {
  const [sort, setSort] = useState<Sort | null>(null)
  const layout = useMemo(() => layoutOf(header), [header])

  const rows = useMemo(() => {
    const built = layout.stations.map((station) => ({
      station,
      values: layout.columns.map(({ name }) => {
        const at = layout.index.get(`${station}\u0000${name}`)
        return (at === undefined ? null : frame?.values[at]) ?? null
      }),
    }))
    if (sort === null) return built
    const sign = sort.descending ? -1 : 1
    return [...built].sort((a, b) => {
      if (sort.key === STATION) return sign * collator.compare(a.station, b.station)
      const x = a.values[sort.key]
      const y = b.values[sort.key]
      if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1 // empty cells last, either way
      return sign * (x - y)
    })
  }, [layout, frame, sort])

  const onSort = (key: number) => setSort((current) => nextSort(current, key))

  return (
    // Not the `Table` wrapper: its `overflow-x-auto` would make the header stick to the
    // wrapper instead of to the screen.
    <table data-slot="table" className="w-full caption-bottom font-mono text-xs">
      <TableCaption>CIM reference: {frame?.header.cimReferenceId ?? header.cimReferenceId ?? 'none'}</TableCaption>
      <TableHeader>
        <TableRow>
          <SortableHead label="Station" sort={sort} column={STATION} onSort={onSort} right={false} />
          {layout.columns.map(({ name, unit }, i) => (
            <SortableHead key={name} label={`${name} (${unit})`} sort={sort} column={i} onSort={onSort} />
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map(({ station, values }) => (
          <TableRow key={station}>
            <TableCell className="font-medium">{station}</TableCell>
            {layout.columns.map(({ name, unit }, i) => (
              <TableCell key={name} className="text-right tabular-nums">
                {format(values[i], unit)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </table>
  )
}
