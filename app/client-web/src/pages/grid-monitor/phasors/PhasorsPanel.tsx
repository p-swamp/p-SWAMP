import { useState } from 'react'
import { CompassIcon, WifiOffIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

import { Panel } from '../Panel'
import { islandColor, islandName } from '../palette'
import type { PanelVariant } from '../variant'
import { PhasorDial } from './PhasorDial'
import { usePhasorsData } from './phasorsContext'

/**
 * Voltage phasors — the web counterpart of p-SWAMP's Qt voltage phasor plot.
 *
 * Reads the same measurement window the frequency dock does — this client's
 * own, one per pipeline. When the recorded line trip separates the northern
 * stations, their phasors drift away from the rest of the dial, coloured by the
 * island the detector assigned them.
 */
export function PhasorsPanel({
  variant = 'dashboard',
}: {
  variant?: PanelVariant
}) {
  const [equalLengths, setEqualLengths] = useState(true)
  const [rotateToMean, setRotateToMean] = useState(true)
  const { state, status, connected } = usePhasorsData()
  const compact = variant === 'dashboard'

  const ready = connected && state !== null
  const islandCount = state
    ? new Set(state.phasors.map((p) => p.island ?? 0)).size
    : 0

  return (
    <Panel
      title="Voltage phasors"
      subtitle="Bus voltage phasors across the Nordic 44 grid, coloured by island"
      status={status}
      ready={ready}
      focusedClassName="w-full max-w-2xl"
      focusHref="/phasors"
      variant={variant}
      minBodyClass="min-h-[320px]"
      badge={
        connected ? (
          <Badge>
            <CompassIcon className="size-3" />
            {state?.phasors.length ?? 0}
          </Badge>
        ) : (
          <Badge variant="outline" className="text-muted-foreground">
            <WifiOffIcon className="size-3" />
            Offline
          </Badge>
        )
      }
      footer={
        state?.mag_ref
          ? `max ${(state.mag_ref / 1e3).toFixed(1)} kV` +
            (state.ang_ref !== null
              ? ` · mean angle ${((state.ang_ref * 180) / Math.PI).toFixed(1)}°`
              : '')
          : undefined
      }
    >
      <div className={compact ? 'flex items-center gap-3' : 'space-y-3'}>
        <PhasorDial
          phasors={state?.phasors ?? []}
          magRef={state?.mag_ref ?? null}
          angRef={state?.ang_ref ?? null}
          equalLengths={equalLengths}
          rotateToMean={rotateToMean}
          size={compact ? 190 : 420}
        />
        <div
          className={
            compact
              ? 'flex min-w-0 flex-col items-start gap-1.5'
              : 'flex flex-wrap items-center justify-center gap-2'
          }
        >
          <Button
            size={compact ? 'xs' : 'sm'}
            variant={equalLengths ? 'default' : 'outline'}
            onClick={() => setEqualLengths((v) => !v)}
          >
            Equal lengths
          </Button>
          <Button
            size={compact ? 'xs' : 'sm'}
            variant={rotateToMean ? 'default' : 'outline'}
            onClick={() => setRotateToMean((v) => !v)}
          >
            Rotate to mean
          </Button>
          {islandCount > 1 &&
            Array.from({ length: islandCount }, (_, i) => (
              <span
                key={i}
                className="flex items-center gap-1.5 text-xs text-muted-foreground"
              >
                <span
                  className="size-2 rounded-full ring-1 ring-foreground/20"
                  style={{ background: islandColor(i) }}
                />
                {islandName(i)}
              </span>
            ))}
        </div>
      </div>
    </Panel>
  )
}
