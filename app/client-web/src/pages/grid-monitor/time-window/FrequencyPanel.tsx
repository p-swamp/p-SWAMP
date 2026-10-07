import { ActivityIcon, WifiOffIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'

import { Panel } from '../Panel'
import { TRACE_COLOR } from '../palette'
import type { PanelVariant } from '../variant'
import { TimeWindowChart } from './TimeWindowChart'
import { useTimeWindowData } from './timeWindowContext'

// A constant per variant on purpose: the height is a dependency of the effect
// that builds the plot, so a measured value would rebuild it on every reflow.
const CHART_HEIGHT = { dashboard: 168, focused: 380 }

const allOneColour = () => TRACE_COLOR

/**
 * System frequency — the Qt main window's "Frequency" dock (`FreqPlot`).
 *
 * Every station's frequency over the last thirty seconds, all in one colour:
 * the point is not to tell stations apart but to see at a glance whether they
 * are still one system. While they are, the traces lie on top of each other;
 * when the grid splits, the band visibly parts.
 *
 * It picks nothing itself — which channels are shown is the provider's
 * decision, since the grid view and an open alarm read the same stream.
 */
export function FrequencyPanel({
  variant = 'dashboard',
}: {
  variant?: PanelVariant
}) {
  const { buffer, subscribe, channels, samplingRate, status, connected, ready } =
    useTimeWindowData()

  return (
    <Panel
      title="Frequency"
      subtitle="Every station's frequency over the last thirty seconds"
      status={status}
      ready={connected && channels.length > 0}
      focusHref="/time-window"
      focusedClassName="w-full max-w-5xl"
      variant={variant}
      minBodyClass="min-h-[260px]"
      contentClassName="p-1"
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
      footer={ready ? `${channels.length} stations · f [Hz]` : undefined}
    >
      <TimeWindowChart
        buffer={buffer}
        subscribe={subscribe}
        channels={channels}
        height={CHART_HEIGHT[variant]}
        legend={false}
        strokeOf={allOneColour}
      />
    </Panel>
  )
}
