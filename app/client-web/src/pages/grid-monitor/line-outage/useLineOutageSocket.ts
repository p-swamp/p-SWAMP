import { useServerSocket } from '@/hooks/useServerSocket'
import { LINE_OUTAGE_WS_PATH } from '@/lib/servers'
import type { Wire } from '@/api/wire'

/** One event as the detector reported it. A line trip shows up once per end
 *  whose current went to zero, so `stations` and `measurements` can be twice as
 *  long as `branches`, which names each branch once, as the grid view does. */
export type LineOutageEvent = Wire['LineOutageEvent']

export type LineOutageState = Wire['LineOutageLog'] | null

export function useLineOutageSocket() {
  const { message, status, connected } =
    useServerSocket<Wire['LineOutageLog']>(LINE_OUTAGE_WS_PATH)

  return { state: message as LineOutageState, status, connected }
}
