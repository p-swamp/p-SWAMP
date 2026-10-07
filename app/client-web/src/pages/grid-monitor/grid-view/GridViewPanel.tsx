import { lazy, Suspense, use, useMemo, useState } from 'react'
import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  LayersIcon,
  RotateCcwIcon,
  WifiOffIcon,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { Panel } from '../Panel'
import { useIslandingData } from '../islanding/islandingContext'
import { useLineOutageData } from '../line-outage/lineOutageContext'
import { islandColor, islandName, PLOT_BACKGROUND } from '../palette'
import { PhasorsContext } from '../phasors/phasorsContext'
import { TimeWindowContext } from '../time-window/timeWindowContext'
import type { PanelVariant } from '../variant'
import { type FieldKind, FIELDS } from './field'
import { createLiveValues, type LiveValues } from './liveValues'
import type { GridLayers, GridViewData, GridViewMode } from './renderer'
import { buildScene } from './scene'
import { useGridModel } from './useGridModel'
import { VoltageFeed } from './VoltageFeed'

// The view itself is fetched when it is first shown, not with the page: it is
// what brings in three.js, which is larger than the rest of the client put
// together and of no use to a page that draws no grid.
const GridView = lazy(() =>
  import('./GridView').then((module) => ({ default: module.GridView })),
)

/** The Qt view's layer names, in the order its layer dialog lists them. */
const LAYER_LABELS: [keyof GridLayers, string][] = [
  ['busNames', 'Bus names'],
  ['buses', 'Buses'],
  ['lines', 'Lines'],
  ['countries', 'Countries'],
  ['islanding', 'Islanding'],
  ['outages', 'Line outages'],
]

/** How many of an island's stations the legend names before trailing off. A
 *  genuine island is a handful of stations; the detector can also briefly
 *  report half the grid as one, and that list would cover the map. */
const MAX_STATIONS_NAMED = 6

/** The colour scale under a field: red below the reference, blue above it,
 *  nothing at it — the Qt heat map's colour bar, laid on its side. */
const FIELD_SCALE =
  'linear-gradient(to right, rgb(255 0 0), rgb(255 0 0 / 0) 50%, rgb(0 0 255 / 0) 50%, rgb(0 0 255))'

/**
 * The voltage entry of the field list.
 *
 * Its own component for one reason: whether the choice can be offered depends
 * on a phasor provider being mounted, and asking that subscribes the asker to
 * the phasor socket. Asked here, the thing that re-renders five times a second
 * is one radio button, and only while the layer list is open.
 */
function VoltageChoice({
  checked,
  onChoose,
}: {
  checked: boolean
  onChoose: () => void
}) {
  const available = use(PhasorsContext) !== null
  return (
    <label
      className={cn(
        'flex items-center gap-2',
        available ? 'cursor-pointer' : 'opacity-50',
      )}
    >
      <input
        type="radio"
        name="grid-field"
        checked={checked}
        disabled={!available}
        onChange={onChoose}
      />
      {FIELDS.voltage.label}
    </label>
  )
}

const ALL_LAYERS: GridLayers = {
  countries: true,
  lines: true,
  buses: true,
  busNames: true,
  islanding: true,
  outages: true,
}

/**
 * The grid view — the central widget of p-SWAMP's Qt main window, and of this
 * one.
 *
 * It is the Qt view's base layers (countries, lines, buses, bus names) with the
 * two things its islanding alarm view and its line-outage layer paint over them
 * left permanently on: branches take the colour of the island they belong to,
 * each island floats above the map by how far its frequency is off nominal, and
 * a branch carrying no current is red. In Qt those appear when an operator opens
 * an alarm; here the grid is the first thing on screen, so it shows the split as
 * it happens rather than once someone has gone looking for it.
 *
 * Three sockets meet here and none of them is this panel's own: islanding
 * decides the colours, line outage the red branches, and the measurement window
 * — when a provider for it is mounted — how high each island rides. It reports
 * the islanding socket's state as its own, since that is the one without which
 * the view says nothing an operator needs.
 */
export function GridViewPanel({
  variant = 'dashboard',
}: {
  variant?: PanelVariant
}) {
  const { model, failed } = useGridModel()
  const { state, status, connected } = useIslandingData()
  const outages = useLineOutageData()
  // Optional: a view mounted without the measurement window still draws, with
  // each island at the mean frequency the detector last reported for it.
  const timeWindow = use(TimeWindowContext)

  const [mode, setMode] = useState<GridViewMode>('3d')
  const [layers, setLayers] = useState<GridLayers>(ALL_LAYERS)
  const [layersOpen, setLayersOpen] = useState(false)
  const [resetSignal, setResetSignal] = useState(0)
  // Off to begin with, as Qt's "Other layers" are.
  const [field, setField] = useState<FieldKind | null>(null)
  const [relief, setRelief] = useState(1)

  const scene = useMemo(() => (model ? buildScene(model) : null), [model])

  const islands = state?.islanding?.islands
  const disconnected = outages.state?.disconnected
  const data = useMemo<GridViewData>(() => {
    const islandOf = new Map<string, number>()
    const islandFreq = new Map<number, number>()
    for (const island of islands ?? []) {
      island.stations.forEach((station) => islandOf.set(station.trim(), island.index))
      if (island.mean_freq !== null) islandFreq.set(island.index, island.mean_freq)
    }
    return {
      islandOf,
      islandFreq,
      disconnected: new Set(disconnected ?? []),
      assessed: islands !== undefined,
    }
  }, [islands, disconnected])

  const buffer = timeWindow?.buffer
  const subscribe = timeWindow?.subscribe
  const frequencies = useMemo<LiveValues | undefined>(() => {
    if (!buffer || !subscribe) return undefined
    return {
      subscribe,
      read: () => {
        const latest = new Map<string, number>()
        buffer.current.channels.forEach((channel, i) => {
          if (channel.measurement !== 'f') return
          const series = buffer.current.series[i]
          const value = series?.[series.length - 1]
          if (value != null && Number.isFinite(value)) {
            latest.set(channel.station.trim(), value)
          }
        })
        return latest
      },
    }
  }, [buffer, subscribe])

  // Written by <VoltageFeed>, which is mounted only while the voltage field is
  // showing; read by the canvas. Nothing in between renders.
  const voltages = useMemo(() => createLiveValues(), [])
  const nominalKv = useMemo(() => {
    const byBus = new Map<string, number>()
    for (const bus of model?.buses ?? []) {
      if (bus.v_nom) byBus.set(bus.name.trim(), bus.v_nom)
    }
    return byBus
  }, [model])

  // Index 0 is the main system, so anything beyond it is a genuine split.
  const separated = (islands ?? []).filter((island) => island.index > 0)
  // Not "open": the detector reports a branch whose current has gone to zero,
  // which a tripped line is, and so is a healthy one a trip has dead-ended.
  const deadBranches = scene
    ? scene.branches.filter((branch) => data.disconnected.has(branch.name)).length
    : 0
  const ready = connected && state !== null

  return (
    <Panel
      title="Grid view"
      subtitle="The Nordic 44 grid, coloured by island and lifted by frequency"
      status={status}
      ready={ready}
      // The topology is static and fetched over HTTP, independently of the
      // sockets that colour it — so the grid is drawn as soon as it loads.
      drawsWithoutData
      focusHref="/islanding"
      variant={variant}
      fill
      contentClassName="overflow-hidden p-0"
      actions={
        <div className="flex items-center gap-1">
          <div className="flex overflow-hidden rounded-md border">
            {(['3d', '2d'] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={mode === option}
                onClick={() => setMode(option)}
                className={cn(
                  'px-2 py-0.5 text-xs font-medium uppercase transition-colors',
                  mode === option
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-background text-muted-foreground hover:text-foreground',
                )}
              >
                {option}
              </button>
            ))}
          </div>
          <Button
            size="xs"
            variant="outline"
            aria-expanded={layersOpen}
            onClick={() => setLayersOpen((open) => !open)}
          >
            <LayersIcon />
            Layers
          </Button>
          <Button
            size="icon-xs"
            variant="outline"
            aria-label="Reset view"
            title="Reset view"
            onClick={() => setResetSignal((n) => n + 1)}
          >
            <RotateCcwIcon />
          </Button>
        </div>
      }
      badge={
        connected ? (
          separated.length > 0 ? (
            <Badge className="border-transparent bg-red-600/20 text-red-700 dark:text-red-400">
              <AlertTriangleIcon className="size-3" />
              {separated.length} island{separated.length > 1 ? 's' : ''}
            </Badge>
          ) : (
            <Badge className="border-transparent bg-emerald-600/15 text-emerald-700 dark:text-emerald-400">
              <CheckCircle2Icon className="size-3" />
              Intact
            </Badge>
          )
        ) : (
          <Badge variant="outline" className="text-muted-foreground">
            <WifiOffIcon className="size-3" />
            Offline
          </Badge>
        )
      }
    >
      <div
        className={cn(
          'relative w-full text-white',
          variant === 'dashboard' ? 'h-full min-h-[320px]' : 'h-[70svh] min-h-[360px]',
        )}
        style={{ background: PLOT_BACKGROUND }}
      >
        {scene ? (
          <Suspense
            fallback={
              <div className="flex size-full items-center justify-center text-sm text-white/60">
                Loading grid view…
              </div>
            }
          >
            <GridView
              scene={scene}
              data={data}
              layers={layers}
              mode={mode}
              resetSignal={resetSignal}
              field={field}
              relief={relief}
              frequencies={frequencies}
              voltages={voltages}
            />
          </Suspense>
        ) : (
          <div className="flex size-full items-center justify-center text-sm text-white/60">
            {failed
              ? 'Could not load the grid model.'
              : model
                ? 'The server sent no diagram to draw the grid from.'
                : 'Loading grid model…'}
          </div>
        )}

        {field === 'voltage' && <VoltageFeed nominalKv={nominalKv} store={voltages} />}

        {layersOpen && (
          <div className="absolute top-2 right-2 z-10 space-y-2 rounded-md bg-black/55 px-3 py-2 text-xs backdrop-blur-sm">
            <fieldset className="space-y-1">
              <legend className="sr-only">Layers</legend>
              {LAYER_LABELS.map(([key, label]) => (
                <label key={key} className="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={layers[key]}
                    onChange={(event) =>
                      setLayers((current) => ({ ...current, [key]: event.target.checked }))
                    }
                  />
                  {label}
                </label>
              ))}
            </fieldset>

            {/* One at a time: two quantities spread over the same map are two
                sets of colours meaning different things in the same place. */}
            <fieldset className="space-y-1 border-t border-white/20 pt-2">
              <legend className="sr-only">Field</legend>
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="grid-field"
                  checked={field === null}
                  onChange={() => setField(null)}
                />
                No heat map
              </label>
              <label
                className={cn(
                  'flex items-center gap-2',
                  frequencies ? 'cursor-pointer' : 'opacity-50',
                )}
              >
                <input
                  type="radio"
                  name="grid-field"
                  checked={field === 'frequency'}
                  disabled={!frequencies}
                  onChange={() => setField('frequency')}
                />
                {FIELDS.frequency.label}
              </label>
              <VoltageChoice
                checked={field === 'voltage'}
                onChoose={() => setField('voltage')}
              />
              {field && mode === '3d' && (
                <label className="flex items-center gap-2 pt-1">
                  Surface height
                  <input
                    type="range"
                    min={0}
                    max={3}
                    step={0.25}
                    value={relief}
                    onChange={(event) => setRelief(Number(event.target.value))}
                    className="w-20"
                  />
                </label>
              )}
            </fieldset>
          </div>
        )}

        {/* The legend of the Qt alarm view's plots — "System", "Island 1" —
            moved onto the grid, where the colours are. */}
        <div className="pointer-events-none absolute bottom-2 left-3 space-y-0.5 text-xs">
          {(islands ?? []).map((island) => (
            <div key={island.index} className="flex items-center gap-2">
              <span
                className="size-2.5 shrink-0 rounded-full"
                style={{ background: islandColor(island.index) }}
              />
              <span className="font-medium">{islandName(island.index)}</span>
              <span className="text-white/65 tabular-nums">
                {island.stations.length} stations
                {island.mean_freq !== null && ` · ${island.mean_freq.toFixed(3)} Hz`}
              </span>
              {island.index > 0 && (
                <span className="font-mono text-white/65">
                  {island.stations.slice(0, MAX_STATIONS_NAMED).join(', ')}
                  {island.stations.length > MAX_STATIONS_NAMED && ', …'}
                </span>
              )}
            </div>
          ))}
          {deadBranches > 0 && (
            <div className="flex items-center gap-2">
              <span className="h-0.5 w-2.5 shrink-0 bg-[#ff3f40]" />
              <span className="font-medium">
                {deadBranches} branch{deadBranches > 1 ? 'es' : ''} carrying no
                current
              </span>
            </div>
          )}
          {islands === undefined && scene && (
            <div className="text-white/60">
              {ready
                ? 'Waiting for the first assessment…'
                : 'Grid shown uncoloured until the detector reports.'}
            </div>
          )}
        </div>

        {field && (
          <div
            className="pointer-events-none absolute right-3 bottom-7 flex items-center gap-2 text-[11px] text-white/80"
            aria-label={`Colour scale: ${FIELDS[field].scaleOf}`}
          >
            <span className="text-white/55">{FIELDS[field].scaleOf}</span>
            <span className="tabular-nums">{FIELDS[field].low}</span>
            <span
              className="h-2 w-28 rounded-sm ring-1 ring-white/25"
              style={{ background: FIELD_SCALE }}
            />
            <span className="tabular-nums">{FIELDS[field].high}</span>
          </div>
        )}

        <div className="pointer-events-none absolute right-3 bottom-2 hidden text-[11px] text-white/40 sm:block">
          {mode === '3d'
            ? 'drag to orbit · shift-drag to pan · scroll to zoom · double-click to reset'
            : 'drag to pan · scroll to zoom · double-click to reset'}
        </div>
      </div>
    </Panel>
  )
}
