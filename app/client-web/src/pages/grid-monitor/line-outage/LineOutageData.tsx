import { type ReactNode, useMemo } from 'react'

import { LineOutageContext } from './lineOutageContext'
import { useLineOutageSocket } from './useLineOutageSocket'

/** Opens the line-outage socket once and shares it with the views beneath. See
 *  `IslandingData` for why this is a provider rather than a hook in the page. */
export function LineOutageData({ children }: { children: ReactNode }) {
  const { state, status, connected } = useLineOutageSocket()
  const value = useMemo(
    () => ({ state, status, connected }),
    [state, status, connected],
  )
  return <LineOutageContext value={value}>{children}</LineOutageContext>
}
