import type { Wire } from '@/api/wire'
import { ISLANDING_DETECTION_WS_PATH } from '@/lib/servers'
import { useServerSocket } from '@/hooks/useServerSocket'

/** What the server pushes, generated from the model in
 *  app/server-python/src/islanding-detection/api.py. */
export type IslandingDetectionState = Wire['IslandingDetectionState']

export function useIslandingDetectionSocket() {
  const { message, status, connected } = useServerSocket<IslandingDetectionState>(ISLANDING_DETECTION_WS_PATH)
  return { state: message, status, connected }
}
