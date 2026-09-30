import { useCallback, useState } from 'react'

import type { Wire } from '@/api/wire'
import { ERRORS_WS_PATH } from '@/lib/servers'
import { useServerSocket } from '@/hooks/useServerSocket'

/** One notice, as the server pushes it (see app/server-python/src/errors/). */
export type ErrorNotice = Wire['ErrorNotice']

/** How many notices the tray keeps; the newest replace the oldest. */
export const VISIBLE_NOTICES = 5

/**
 * The error feed: operational failures in this browser's pipeline runs, on
 * whatever page it shows. In `src/hooks/` because its user is the layout, which
 * outlives navigation. It keeps the last few notices and lets the person
 * dismiss one. A notice replayed after a reconnect is recognised by its id.
 */
export function useErrorFeed() {
  const [notices, setNotices] = useState<ErrorNotice[]>([])
  const [seen] = useState(() => new Set<string>())

  const { connected } = useServerSocket<ErrorNotice>(ERRORS_WS_PATH, {
    onMessage: (notice) => {
      if (seen.has(notice.id)) return
      seen.add(notice.id)
      setNotices((prev) => [notice, ...prev].slice(0, VISIBLE_NOTICES))
    },
  })

  const dismiss = useCallback((id: string) => {
    setNotices((prev) => prev.filter((notice) => notice.id !== id))
  }, [])

  return { notices, dismiss, connected }
}
