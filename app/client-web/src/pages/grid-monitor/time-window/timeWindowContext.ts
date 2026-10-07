import { createContext, use } from 'react'

import type { useTimeWindowSocket } from './useTimeWindowSocket'

export type TimeWindowValue = ReturnType<typeof useTimeWindowSocket> & {
  /** Connected, and showing the channels the provider was asked for. */
  ready: boolean
}

/**
 * The time-window socket, shared by the views of the main window that read it.
 *
 * The frequency dock, the grid view and an open islanding alarm all want the
 * same thing — every station's frequency, live — so they read one socket rather
 * than opening three, which the server would count as three views with three
 * selections.
 *
 * Split from the provider component so this module exports no component:
 * `react-refresh/only-export-components` is an error in this repo.
 */
export const TimeWindowContext = createContext<TimeWindowValue | null>(null)

export function useTimeWindowData(): TimeWindowValue {
  const value = use(TimeWindowContext)
  if (value === null) {
    throw new Error('useTimeWindowData must be used inside <TimeWindowData>')
  }
  return value
}
