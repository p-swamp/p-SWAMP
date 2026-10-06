import { createContext, use } from 'react'

import type { ConnStatus } from '@/hooks/useServerSocket'

import type { LineOutageState } from './useLineOutageSocket'

export type LineOutageValue = {
  state: LineOutageState
  status: ConnStatus
  connected: boolean
}

/**
 * The line-outage socket, shared by the two views that read it: the event log,
 * and the grid view, which paints an open branch red.
 *
 * Split from the provider component so this module exports no component:
 * `react-refresh/only-export-components` is an error in this repo.
 */
export const LineOutageContext = createContext<LineOutageValue | null>(null)

export function useLineOutageData(): LineOutageValue {
  const value = use(LineOutageContext)
  if (value === null) {
    throw new Error('useLineOutageData must be used inside <LineOutageData>')
  }
  return value
}
