import { useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { useChannelCatalogue } from './useChannelCatalogue'
import type { ChannelInfo } from './useTimeWindowSocket'

/** Cap on how many traces can be shown at once — past this they stop being
 *  readable, and the Qt plot draws the same line at 50. */
const MAX_SELECTED = 12

export function ChannelPicker({
  selected,
  onChange,
}: {
  selected: ChannelInfo[]
  onChange: (indices: number[]) => void
}) {
  const { channels: all, failed } = useChannelCatalogue()
  const [measurement, setMeasurement] = useState('f')

  const measurements = useMemo(
    () => [...new Set(all.map((c) => c.measurement))],
    [all],
  )
  const visible = useMemo(
    () => all.filter((c) => c.measurement === measurement),
    [all, measurement],
  )
  const selectedIdx = useMemo(
    () => new Set(selected.map((c) => c.idx)),
    [selected],
  )

  const toggle = (channel: ChannelInfo) => {
    const next = new Set(selectedIdx)
    if (next.has(channel.idx)) {
      // Never leave the chart with nothing to draw.
      if (next.size === 1) return
      next.delete(channel.idx)
    } else {
      if (next.size >= MAX_SELECTED) return
      next.add(channel.idx)
    }
    onChange([...next])
  }

  if (failed)
    return (
      <p className="text-sm text-muted-foreground">Could not load the channel list.</p>
    )
  if (all.length === 0)
    return <p className="text-sm text-muted-foreground">Loading channels…</p>

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Measurement</span>
        {measurements.map((m) => (
          <Button
            key={m}
            size="sm"
            variant={m === measurement ? 'default' : 'outline'}
            onClick={() => setMeasurement(m)}
          >
            {m}
          </Button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {selectedIdx.size}/{MAX_SELECTED} shown
        </span>
      </div>

      <div className="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto">
        {visible.map((channel) => {
          const on = selectedIdx.has(channel.idx)
          return (
            <Badge
              key={channel.idx}
              variant={on ? 'default' : 'outline'}
              className={cn(
                'cursor-pointer select-none font-mono text-xs',
                !on && 'text-muted-foreground',
              )}
              onClick={() => toggle(channel)}
            >
              {channel.station}
            </Badge>
          )
        })}
      </div>
    </div>
  )
}
