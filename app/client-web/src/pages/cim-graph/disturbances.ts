import type { MenuTarget } from './GridMap'
import { CLEAR_MS } from './useCimGraphSocket'

/** What the page's hook offers: each disturbance, sent to the simulation only. */
export type Disturb = {
  trip: (mrid: string) => void
  reconnect: (mrid: string) => void
  shortCircuit: (node: string) => void
  clearShortCircuit: (node: string) => void
  fault: (line: string, end: 1 | 2) => void
  loadStep: (load: string, p_mw: number) => void
}

export type Item = { label: string; run: () => void; hint?: string }

/** The load steps offered, as a factor of the load's power as the graph has it. */
const STEPS = [1.2, 1.5, 0.8, 0.5]

/** The disturbances of ``target``, and their undoing: what its menu and its panel offer. */
export function disturbancesOf(target: MenuTarget, disturb: Disturb): { title: string; items: Item[] } {
  if (target.kind === 'generator') return { title: target.generator.name, items: [] } // none of a machine, yet
  if (target.kind === 'branch') {
    const { branch } = target
    const items: Item[] = [
      { label: 'Trip', run: () => disturb.trip(branch.mrid), hint: 'as no one commanded it: the graph is not told' },
      { label: 'Reconnect', run: () => disturb.reconnect(branch.mrid) },
    ]
    if (branch.kind === 'line') {
      for (const end of [1, 2] as const) {
        items.push({
          label: `Fault at end ${end}, cleared`,
          run: () => disturb.fault(branch.mrid, end),
          hint: `its protection opens its breakers after ${CLEAR_MS} ms`,
        })
      }
    }
    return { title: branch.name, items }
  }
  if (target.kind === 'substation') {
    const { substation } = target
    const items = substation.nodes.flatMap((node): Item[] => {
      const name = `${node.name}${node.nominal_kv === null ? '' : ` (${node.nominal_kv} kV)`}`
      return [
        { label: `Short circuit at ${name}`, run: () => disturb.shortCircuit(node.mrid) },
        { label: `Clear it at ${name}`, run: () => disturb.clearShortCircuit(node.mrid) },
      ]
    })
    return { title: substation.name, items }
  }
  const { load } = target
  const p = load.p_mw
  const items: Item[] =
    p === null
      ? []
      : STEPS.map((factor) => ({
          label: `Step to ${(p * factor).toFixed(0)} MW (${factor > 1 ? '+' : '−'}${Math.round(Math.abs(factor - 1) * 100)} %)`,
          run: () => disturb.loadStep(load.mrid, p * factor),
        }))
  return { title: load.name, items }
}
