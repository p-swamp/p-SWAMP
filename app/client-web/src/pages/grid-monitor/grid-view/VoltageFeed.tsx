import { use, useEffect } from 'react'

import { PhasorsContext } from '../phasors/phasorsContext'
import type { LiveValueStore } from './liveValues'

/**
 * Feeds the grid view each station's voltage, per unit of its nominal.
 *
 * A component that renders nothing, so that subscribing to the phasor socket is
 * something the grid view can switch on and off: mounted only while the voltage
 * field is showing, it is the one thing that re-renders when a snapshot lands,
 * and what it does with the snapshot is write it into a store the canvas reads.
 * The panel around it never hears about it.
 *
 * Per unit as `Voltage3DLayer` computes it: magnitude in volts over the bus's
 * nominal voltage, which the grid model gives in kilovolts.
 */
export function VoltageFeed({
  nominalKv,
  store,
}: {
  nominalKv: Map<string, number>
  store: LiveValueStore
}) {
  const phasors = use(PhasorsContext)?.state?.phasors

  useEffect(() => {
    const perUnit = new Map<string, number>()
    for (const phasor of phasors ?? []) {
      const station = phasor.station.trim()
      const nominal = nominalKv.get(station)
      if (phasor.mag !== null && nominal) perUnit.set(station, phasor.mag / (nominal * 1e3))
    }
    store.set(perUnit)
  }, [phasors, nominalKv, store])

  return null
}
