import type { Wire } from '@/api/wire'
import { STATE_ESTIMATOR_WS_PATH } from '@/lib/servers'
import { useServerSocket } from '@/hooks/useServerSocket'

/** What the server pushes, generated from the model in
 *  app/server-python/src/state_estimator/api.py. */
export type StateEstimatorState = Wire['StateEstimatorState']

export function useStateEstimatorSocket() {
  const { message, status, connected } = useServerSocket<StateEstimatorState>(STATE_ESTIMATOR_WS_PATH)
  return { state: message, status, connected }
}
