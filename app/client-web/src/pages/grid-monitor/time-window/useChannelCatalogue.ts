import { useEffect, useState } from 'react'

import type { Wire } from '@/api/wire'
import { resolveApiUrl, TIME_WINDOW_API_PATH } from '@/lib/servers'

import type { ChannelInfo } from './useTimeWindowSocket'

// Static for the life of the server, so one fetch serves every view that asks.
// A failed fetch is forgotten, so the next view to mount tries again.
let pending: Promise<ChannelInfo[]> | null = null

function loadCatalogue(): Promise<ChannelInfo[]> {
  pending ??= fetch(resolveApiUrl(`${TIME_WINDOW_API_PATH}/channels`))
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then((body: Wire['ChannelCatalogue']) => body.channels)
    .catch((error) => {
      pending = null
      throw error
    })
  return pending
}

/** Every selectable channel (`GET /api/time-window/channels`). Empty until it
 *  has loaded; `failed` once it could not be. */
export function useChannelCatalogue(): { channels: ChannelInfo[]; failed: boolean } {
  const [state, setState] = useState<{ channels: ChannelInfo[]; failed: boolean }>({
    channels: [],
    failed: false,
  })

  useEffect(() => {
    let live = true
    loadCatalogue().then(
      (channels) => live && setState({ channels, failed: false }),
      () => live && setState({ channels: [], failed: true }),
    )
    return () => {
      live = false
    }
  }, [])

  return state
}
