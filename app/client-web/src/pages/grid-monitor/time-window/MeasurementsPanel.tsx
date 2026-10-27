import { ActivityIcon, WifiOffIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'

import { Panel } from '../Panel'
import type { PanelVariant } from '../variant'
import { ChannelPicker } from './ChannelPicker'
import { TimeWindowChart } from './TimeWindowChart'
import { useTimeWindowSocket } from './useTimeWindowSocket'

/**
 * Live measurements — a moving window of the PMU stream, as the monitoring
 * applications see it. The web counterpart of p-SWAMP's Qt time window plot.
 *
 * With the default frequency channels selected, a disturbance is visible
 * directly: take lines out on the CIM graph page until part of the grid is
 * separated, and its stations move onto a frequency of their own.
 *
 * The chart height is a constant per variant on purpose — it is a dependency of
 * the effect that builds the plot, so a measured value would destroy and rebuild
 * the plot on every reflow.
 */
const CHART_HEIGHT = { dashboard: 260, focused: 380 }

export function MeasurementsPanel({
  variant = 'dashboard',
}: {
  variant?: PanelVariant
}) {
  const { buffer, subscribe, channels, samplingRate, status, connected, selectChannels } =
    useTimeWindowSocket()

  const ready = connected && channels.length > 0

  return (
    <Panel
      title="Live Measurements"
      subtitle="A moving window of the live grid's PMU stream, as the modules see it"
      status={status}
      ready={ready}
      focusedClassName="w-full max-w-5xl"
      focusHref="/time-window"
      variant={variant}
      minBodyClass="min-h-[260px]"
      badge={
        connected ? (
          <Badge>
            <ActivityIcon className="size-3" />
            {samplingRate ? `${samplingRate} Hz` : 'Live'}
          </Badge>
        ) : (
          <Badge variant="outline" className="text-muted-foreground">
            <WifiOffIcon className="size-3" />
            Offline
          </Badge>
        )
      }
      footer={
        ready ? `${channels.length} channels · ${samplingRate ?? '?'} Hz` : undefined
      }
    >
      <div className="space-y-4">
        <TimeWindowChart
          buffer={buffer}
          subscribe={subscribe}
          channels={channels}
          height={CHART_HEIGHT[variant]}
        />
        <ChannelPicker selected={channels} onChange={selectChannels} />
      </div>
    </Panel>
  )
}
