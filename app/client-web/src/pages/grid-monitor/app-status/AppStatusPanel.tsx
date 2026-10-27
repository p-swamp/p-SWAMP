import { RadioIcon, WifiOffIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'

import { Panel } from '../Panel'
import type { PanelVariant } from '../variant'
import { AppStatusTable } from './AppStatusTable'
import { useAppStatusSocket } from './useAppStatusSocket'

/**
 * Which modules are analysing the live grid and what they report — the web
 * counterpart of p-SWAMP's Qt status dock — and the feed they all read.
 *
 * There is one grid and one simulation of it, so every browser sees the same
 * rows. The Qt version's Stop and Open-console buttons are deliberately absent:
 * a module is configured by its pipeline file, not stopped from a page.
 */
export function AppStatusPanel({
  variant = 'dashboard',
}: {
  variant?: PanelVariant
}) {
  const { state, status, connected } = useAppStatusSocket()
  const feed = state?.feed
  const ready = connected && state !== null

  return (
    <Panel
      title="Status"
      subtitle="Modules analysing the live grid simulation"
      status={status}
      ready={ready}
      focusedClassName="w-full max-w-3xl"
      focusHref="/app-status"
      variant={variant}
      minBodyClass="min-h-[152px]"
      contentClassName="p-0"
      badge={
        connected ? (
          <Badge variant={feed?.streaming ? 'default' : 'secondary'}>
            <RadioIcon className="size-3" />
            {feed?.streaming ? 'Streaming' : 'Stopped'}
          </Badge>
        ) : (
          <Badge variant="outline" className="text-muted-foreground">
            <WifiOffIcon className="size-3" />
            Offline
          </Badge>
        )
      }
      // The one view of the feed itself anywhere in the grid monitor — keep it.
      footer={
        feed
          ? feed.error
            ? `Live simulation down: ${feed.error}`
            : `Live simulation (${feed.source}) · ${feed.n_channels} channels @ ${feed.data_rate} Hz`
          : undefined
      }
    >
      <AppStatusTable
        apps={state?.apps ?? []}
        serverTime={state?.server_time ?? 0}
        variant={variant}
      />
    </Panel>
  )
}
