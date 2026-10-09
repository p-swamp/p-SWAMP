import { useCallback } from 'react'

import type { Wire } from '@/api/wire'
import { fireCommand, postCommand } from '@/lib/commands'
import { ROLLING_FREQUENCY_API_PATH, ROLLING_FREQUENCY_WS_PATH } from '@/lib/servers'
import { useServerSocket } from '@/hooks/useServerSocket'

/** What the server pushes, generated from the model in
 *  app/server-python/src/rolling_frequency/api.py. */
export type RollingFrequencyState = Wire['RollingFrequencyState']

const fire = (promise: Promise<void>) => fireCommand('rolling-frequency', promise)

/**
 * The page's socket and its player commands. Each command is a POST; its
 * effect arrives as the next state. One the player refuses is a 409, which
 * `fireCommand` logs.
 */
export function useRollingFrequencySocket() {
  const { message, status, connected } = useServerSocket<RollingFrequencyState>(ROLLING_FREQUENCY_WS_PATH)

  const play = useCallback(() => fire(postCommand(`${ROLLING_FREQUENCY_API_PATH}/playback/play`)), [])
  const pause = useCallback(() => fire(postCommand(`${ROLLING_FREQUENCY_API_PATH}/playback/pause`)), [])
  const seek = useCallback(
    (offsetS: number) =>
      fire(postCommand(`${ROLLING_FREQUENCY_API_PATH}/playback/seek`, { body: { offset_s: offsetS } })),
    [],
  )
  const setSpeed = useCallback(
    (speed: number) => fire(postCommand(`${ROLLING_FREQUENCY_API_PATH}/playback/speed`, { body: { speed } })),
    [],
  )

  return { state: message, status, connected, play, pause, seek, setSpeed }
}
