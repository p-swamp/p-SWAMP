import { useEffect, useState } from 'react'
import { PauseIcon, PlayIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

import { useRollingFrequencySocket } from './useRollingFrequencySocket'

const SPEEDS = ['1', '2', '5', '10']

/** The recording has a frame every 0.1 s. */
const STEP_S = 0.1

/** Seconds from one ISO instant to another. */
function secondsBetween(from?: string | null, to?: string | null): number | null {
  return from && to ? (new Date(to).getTime() - new Date(from).getTime()) / 1000 : null
}

/**
 * The Rolling frequency page (route `/rolling-frequency`): a module with a
 * five-second window, over a 30 s recording. The module answers nothing while
 * its window fills, which it does again after every seek. The server keeps the
 * results it has computed for the recording, so seeking back over a part
 * already played shows the result at once, and says it came from the cache.
 */
export function RollingFrequencyPage() {
  const { state, connected, play, pause, seek, setSpeed } = useRollingFrequencySocket()

  // The slider position while dragged; null when it follows the cursor. One
  // seek on release, listened for on the window so a release anywhere counts.
  const [scrub, setScrub] = useState<number | null>(null)
  useEffect(() => {
    if (scrub === null) return
    const commit = () => {
      seek(scrub)
      setScrub(null)
    }
    const timer = setTimeout(commit, 1000)
    window.addEventListener('pointerup', commit)
    window.addEventListener('pointercancel', commit)
    return () => {
      clearTimeout(timer)
      window.removeEventListener('pointerup', commit)
      window.removeEventListener('pointercancel', commit)
    }
  }, [scrub, seek])

  const player = state?.player
  const playing = player !== undefined && !player.paused
  const offset = secondsBetween(player?.coverage_start, player?.cursor) ?? 0
  const duration = secondsBetween(player?.coverage_start, player?.coverage_end) ?? 0
  const canSeek = connected && player?.can_seek === true
  const result = state?.result?.result
  const windowS = state?.warm_up_s ?? 5

  return (
    <Card className="w-full max-w-xl">
      <CardHeader>
        <CardTitle>Rolling frequency</CardTitle>
        <CardAction>
          <Badge variant={connected ? 'default' : 'outline'}>{connected ? 'Online' : 'Offline'}</Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="text-sm text-muted-foreground tabular-nums" data-testid="cursor">
          t = {offset.toFixed(1)} s of {duration.toFixed(0)} s · {playing ? 'Playing' : 'Paused'}
        </div>
        {result ? (
          <div className="flex flex-wrap items-baseline gap-3">
            <span className="text-2xl tabular-nums" data-testid="result">
              {result.mean_hz.toFixed(4)} Hz
            </span>
            <Badge variant={state?.from_cache ? 'secondary' : 'outline'} data-testid="origin">
              {state?.from_cache ? 'From cache' : 'Computed now'}
            </Badge>
            <span className="w-full text-sm text-muted-foreground">
              Mean over the last {result.window_s} s ({result.samples} frames).
            </span>
          </div>
        ) : (
          <div className="text-muted-foreground" data-testid="filling">
            Window filling: the module needs {windowS} s of unbroken frames before it answers.
          </div>
        )}
        <p className="text-sm text-muted-foreground">
          Play past {windowS} s, then drag the slider back over what has played: the result is there at
          once, kept from the earlier pass. Drag it forward to a part nobody has played and the window
          has to fill again.
        </p>
      </CardContent>
      <CardFooter className="flex-col gap-3">
        <div className="flex w-full items-center gap-3 text-xs text-muted-foreground">
          <span className="whitespace-nowrap tabular-nums">0 s</span>
          <input
            type="range"
            aria-label="Seek"
            className="w-full"
            min={0}
            max={Math.max(duration - STEP_S, 0)}
            step={STEP_S}
            value={scrub ?? offset}
            disabled={!canSeek}
            onChange={(event) => setScrub(Number(event.target.value))}
          />
          <span className="whitespace-nowrap tabular-nums">{duration.toFixed(0)} s</span>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button variant={connected && !playing ? 'default' : 'outline'} size="icon" aria-label="Play" disabled={!connected} onClick={play}>
            <PlayIcon />
          </Button>
          <Button variant={playing ? 'default' : 'outline'} size="icon" aria-label="Pause" disabled={!connected} onClick={pause}>
            <PauseIcon />
          </Button>
          <Select value={player ? String(player.speed) : '1'} onValueChange={(value) => setSpeed(Number(value))} disabled={!connected}>
            <SelectTrigger className="w-24" aria-label="Speed">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SPEEDS.map((speed) => (
                <SelectItem key={speed} value={speed}>
                  {speed}×
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardFooter>
    </Card>
  )
}
