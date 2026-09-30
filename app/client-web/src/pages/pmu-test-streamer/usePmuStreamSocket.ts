import { useCallback, useState } from 'react'

import { fireCommand, postCommand } from '@/lib/commands'
import { PMU_STREAM_API_PATH, PMU_STREAM_WS_PATH } from '@/lib/servers'
import { useServerSocket } from '@/hooks/useServerSocket'
import type { Wire } from '@/api/wire'

/** What the server pushes on connect and after every change (`state_message`
 *  in app/server-python/src/pmu_test_streamer/api.py). Its parts are the core's
 *  own messages, generated from the same Python classes. */
export type PmuStreamState = Wire['PmuStreamState']
export type PmuHeader = Wire['PmuHeader']
export type PmuFrame = Wire['PmuFrame']
export type PlayerStatus = Wire['PlayerStatus']

const fire = (promise: Promise<void>) => fireCommand('pmu-test-streamer', promise)

/**
 * The streamer's socket and commands. Each command is a POST that becomes a
 * typed command for this client's player; the effect arrives as the next state.
 * A command that does not apply now is a 409, which `fireCommand` logs; the
 * page renders its controls from `player` so it does not offer one.
 */
export function usePmuStreamSocket() {
  const { message, status, connected } = useServerSocket<PmuStreamState>(PMU_STREAM_WS_PATH)

  // Every frame carries its layout; keep the last one so the table keeps its
  // rows while no frame is at hand. Compared by header_id, a content hash.
  const [header, setHeader] = useState<PmuHeader | null>(null)
  const seen = message?.frame?.header
  if (seen && seen.header_id !== header?.header_id) setHeader(seen)

  const play = useCallback(() => fire(postCommand(`${PMU_STREAM_API_PATH}/playback/play`)), [])
  const pause = useCallback(() => fire(postCommand(`${PMU_STREAM_API_PATH}/playback/pause`)), [])
  const step = useCallback(
    (n: number) => fire(postCommand(`${PMU_STREAM_API_PATH}/playback/step`, { body: { n } })),
    [],
  )
  const seek = useCallback(
    (offsetS: number, endOffsetS: number | null = null, playing = false) =>
      fire(
        postCommand(`${PMU_STREAM_API_PATH}/playback/seek`, {
          body: { offset_s: offsetS, end_offset_s: endOffsetS, play: playing },
        }),
      ),
    [],
  )
  const setSpeed = useCallback(
    (speed: number) => fire(postCommand(`${PMU_STREAM_API_PATH}/playback/speed`, { body: { speed } })),
    [],
  )
  const switchSource = useCallback(
    (name: string) => fire(postCommand(`${PMU_STREAM_API_PATH}/playback/source`, { body: { name } })),
    [],
  )

  return { state: message, header, status, connected, play, pause, step, seek, setSpeed, switchSource }
}
