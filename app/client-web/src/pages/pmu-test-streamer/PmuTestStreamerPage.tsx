import { PauseIcon, PlayIcon, SkipBackIcon, SkipForwardIcon, WifiOffIcon } from 'lucide-react'

import { usePmuStreamSocket } from './usePmuStreamSocket'
import { FrameTable } from './FrameTable'
import { Timeline } from './Timeline'
import { addSeconds, formatUtc, secondsBetween } from './time'
import { Alert, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const SPEEDS = ['0.5', '1', '2', '5']

/**
 * The PMU test streamer (route `/pmu-test-streamer`): the server data
 * architecture's worked example, seen from the browser. It renders the frame at
 * the player's cursor, the stats module's result for it, the configured
 * sources, and the replay controls, all from the player's own status, so a
 * control that does not apply (any of them, while live) is disabled.
 */
export function PmuTestStreamerPage() {
  const {
    state,
    header,
    status,
    connected,
    play,
    pause,
    step,
    seek,
    setSpeed,
    switchSource,
    setAutoPause,
    summarize,
  } = usePmuStreamSocket()

  const player = state?.player
  const live = player?.mode === 'live'
  const playing = player !== undefined && !player.paused && !live
  const interval = header ? 1 / header.data_rate : 0.05
  // The next second from the frame at the cursor, cut at the coverage's end.
  const cursorAt = state?.frame?.timestamp ?? null
  const chunkSeconds = Math.min(1, secondsBetween(cursorAt, player?.coverage_end) ?? 0)
  const controls = connected && !live
  const canSeek = controls && player?.can_seek === true
  const stats = state?.stats?.result
  const excursion = state?.excursion?.result
  const summary = state?.summary?.result

  return (
    <Card className="w-full max-w-3xl gap-0">
      <CardHeader className="border-b">
        <CardTitle className="text-lg">PMU Test Streamer</CardTitle>
        <div className="text-gray-500">
          A PMU source through the core pipeline: source → frame statistics →
          excursion, with a range summary on request. E2E example and used for integration testing. <em> Do not use this page to do p-SWAMP experiments; use <code>pswamp new subapp</code> to generate a new
          page/subapp instead. 🙂</em>
          <table className="mt-3 text-sm [&_th]:pr-4 [&_th]:text-left [&_th]:font-medium">
            <tbody>
              <tr><th>f</th><td>frequency</td></tr>
              <tr><th>df</th><td>rate of change of frequency</td></tr>
              <tr><th>P</th><td>active power</td></tr>
              <tr><th>Q</th><td>reactive power</td></tr>
              <tr><th>v_dev</th><td>voltage deviation</td></tr>
              <tr><th>VUF</th><td>voltage unbalance</td></tr>
            </tbody>
          </table>
        </div>
        <CardAction className="self-center">
          {connected && live ? (
            <Badge className="bg-red-600 text-white" aria-label="Live">
              <span className="size-2 animate-pulse rounded-full bg-white" aria-hidden />
              LIVE
            </Badge>
          ) : connected ? (
            <Badge variant={playing ? 'default' : 'secondary'}>
              Recorded · {player?.ended ? 'Ended' : playing ? 'Playing' : 'Paused'}
            </Badge>
          ) : (
            <Badge variant="outline" className="text-muted-foreground">
              <WifiOffIcon className="size-3" />
              Offline
            </Badge>
          )}
        </CardAction>
      </CardHeader>

      <CardContent className="px-6 py-4">
        {connected && header ? (
          <FrameTable header={header} frame={state?.frame ?? null} />
        ) : (
          <div className="flex min-h-[152px] items-center justify-center">
            <Alert variant={status.kind === 'offline' && status.isError ? 'destructive' : 'default'} className="w-auto">
              <AlertTitle>{status.kind === 'online' ? 'Waiting for a frame…' : status.label}</AlertTitle>
            </Alert>
          </div>
        )}
        {player?.error && (
          <Alert variant="destructive" className="mt-3">
            <AlertTitle>{player.error}</AlertTitle>
          </Alert>
        )}
      </CardContent>

      <CardFooter className="flex-col gap-4 border-t pt-6">
        {/* The configured sources; the active one is pressed (red when live). */}
        <div role="group" aria-label="Source" className="inline-flex items-center gap-1 rounded-lg border p-1">
          {(player?.sources ?? []).map((name) => {
            const active = player?.source === name
            return (
              <Button
                key={name}
                size="sm"
                variant={active ? 'default' : 'ghost'}
                className={active && live ? 'bg-red-600 text-white hover:bg-red-600/90' : undefined}
                aria-pressed={active}
                disabled={!connected}
                onClick={() => !active && switchSource(name)}
              >
                {name}
              </Button>
            )
          })}
        </div>

        <div className="grid w-full grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1 text-sm">
          <span className="text-right text-muted-foreground">Frame</span>
          <span className="tabular-nums" data-testid="frame-readout">
            {state?.frame ? `${live ? 'Live · ' : ''}${formatUtc(state.frame.timestamp)}` : '—'}
          </span>
          <span className="text-right text-muted-foreground">Stats</span>
          <span className="tabular-nums" data-testid="stats-readout">
            {stats?.mean_frequency_hz != null
              ? `mean f ${stats.mean_frequency_hz.toFixed(4)} Hz · spread ${stats.angle_spread_deg?.toFixed(2) ?? '—'}° · ${stats.n_stations} stations`
              : '—'}
          </span>
          <span className="text-right text-muted-foreground">Excursion</span>
          <span className="flex items-center gap-3 tabular-nums" data-testid="excursion-readout">
            {excursion ? (
              <>
                <Badge variant={excursion.in_band ? 'secondary' : 'destructive'}>
                  {excursion.in_band ? 'in band' : 'out of band'}
                </Badge>
                ±{(excursion.band_hz * 1000).toFixed(0)} mHz · {excursion.excursions} so far
              </>
            ) : (
              '—'
            )}
            <label className="ml-auto flex items-center gap-1 text-xs">
              <input
                type="checkbox"
                aria-label="Pause on excursion"
                checked={excursion?.auto_pause ?? false}
                disabled={!controls}
                onChange={(event) => setAutoPause(event.target.checked)}
              />
              pause on excursion
            </label>
          </span>
          <span className="text-right text-muted-foreground">Summary</span>
          <span className="flex items-center gap-3 tabular-nums" data-testid="summary-readout">
            {summary
              ? `${summary.source} · ${formatUtc(summary.start)} + ${(secondsBetween(summary.start, summary.end) ?? 0).toFixed(2)} s · ${summary.frames} frames · f ${summary.min_frequency_hz.toFixed(4)}–${summary.max_frequency_hz.toFixed(4)} Hz`
              : '—'}
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              disabled={!connected || !player || !cursorAt}
              onClick={() => player && cursorAt && summarize(player.source, cursorAt, addSeconds(cursorAt, 1))}
            >
              Summarize next 1 s
            </Button>
          </span>
        </div>

        <Timeline player={player} cursorAt={cursorAt} interval={interval} playing={playing} canSeek={canSeek} seek={seek} />

        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button variant="outline" size="icon" aria-label="Step back" disabled={!canSeek} onClick={() => step(-1)}>
            <SkipBackIcon />
          </Button>
          <Button variant={controls && !playing ? 'default' : 'outline'} size="icon" aria-label="Play" disabled={!controls} onClick={play}>
            <PlayIcon />
          </Button>
          <Button variant={playing ? 'default' : 'outline'} size="icon" aria-label="Pause" disabled={!controls} onClick={pause}>
            <PauseIcon />
          </Button>
          <Button variant="outline" size="icon" aria-label="Step forward" disabled={!controls} onClick={() => step(1)}>
            <SkipForwardIcon />
          </Button>
          <Select value={player ? String(player.speed) : '1'} onValueChange={(value) => setSpeed(Number(value))} disabled={!controls}>
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
          {/* A chunk: seek with an end. The player plays one second and stops there. */}
          <Button
            variant="outline"
            size="sm"
            disabled={!canSeek || !cursorAt || chunkSeconds <= 0}
            onClick={() => cursorAt && seek(cursorAt, addSeconds(cursorAt, chunkSeconds), true)}
          >
            Play next 1 s
          </Button>
        </div>
      </CardFooter>
    </Card>
  )
}
