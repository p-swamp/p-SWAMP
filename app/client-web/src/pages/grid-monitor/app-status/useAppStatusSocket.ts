import { useServerSocket } from '@/hooks/useServerSocket'
import { APP_STATUS_WS_PATH } from '@/lib/servers'
import type { Wire } from '@/api/wire'

/** One application's row, and the statuses it can report. Straight from the
 *  contract — the pydantic models in app/server-python/src/pswamp_web/wire.py,
 *  not a hand-copy of them, so a field added there is visible here at once. */
export type AppStatusRow = Wire['AppStatus']
export type AppStatusValue = AppStatusRow['status']

/** The PMU stream every application reads: the live grid simulation. */
export type FeedState = Wire['FeedStatus']

export function useAppStatusSocket() {
  const { message, status, connected } =
    useServerSocket<Wire['AppStatusTable']>(APP_STATUS_WS_PATH)

  return { state: message, status, connected }
}
