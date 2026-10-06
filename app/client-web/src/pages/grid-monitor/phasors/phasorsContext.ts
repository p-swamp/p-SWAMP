import { createContext, use } from 'react'

import type { ConnStatus } from '@/hooks/useServerSocket'

import type { PhasorsState } from './usePhasorsSocket'

export type PhasorsValue = {
  state: PhasorsState | null
  status: ConnStatus
  connected: boolean
}

/**
 * The phasor socket, shared by the two views that read it: the phasor dock, and
 * the islanding alarm view, which draws the same phasors beside the frequencies
 * of the islands they belong to.
 *
 * Split from the provider component so this module exports no component:
 * `react-refresh/only-export-components` is an error in this repo.
 */
export const PhasorsContext = createContext<PhasorsValue | null>(null)

export function usePhasorsData(): PhasorsValue {
  const value = use(PhasorsContext)
  if (value === null) {
    throw new Error('usePhasorsData must be used inside <PhasorsData>')
  }
  return value
}
