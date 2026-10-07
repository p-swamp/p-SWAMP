import { type ReactNode, useMemo } from 'react'

import { PhasorsContext } from './phasorsContext'
import { usePhasorsSocket } from './usePhasorsSocket'

/** Opens the phasor socket once and shares it with the views beneath. See
 *  `IslandingData` for why this is a provider rather than a hook in the page. */
export function PhasorsData({ children }: { children: ReactNode }) {
  const { state, status, connected } = usePhasorsSocket()
  const value = useMemo(
    () => ({ state, status, connected }),
    [state, status, connected],
  )
  return <PhasorsContext value={value}>{children}</PhasorsContext>
}
