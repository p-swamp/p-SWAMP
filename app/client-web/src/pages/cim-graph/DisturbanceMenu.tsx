import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { MenuRequest } from './GridMap'
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

type Item = { label: string; run: () => void; hint?: string }

/** The load steps offered, as a factor of the load's power as the graph has it. */
const STEPS = [1.2, 1.5, 0.8, 0.5]

/** The menu's items for what was right-clicked: its disturbances, and their undoing. */
function itemsFor(request: MenuRequest, disturb: Disturb): { title: string; items: Item[] } {
  const { target } = request
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

/**
 * The disturbances of what was right-clicked on the map, at the click: a line or transformer (trip,
 * reconnect, a fault cleared by its protection), a substation (a short circuit at one of its nodes)
 * or a load (a step). Each goes to the simulation only; what comes of it shows in the event log, and
 * what its protection opens, on the map. Escape or a click elsewhere closes it. It stays inside the
 * map's box, however near its edge the click was.
 */
export function DisturbanceMenu({
  request,
  disturb,
  onClose,
}: {
  request: MenuRequest
  disturb: Disturb
  onClose: () => void
}) {
  const box = useRef<HTMLDivElement | null>(null)
  const [at, setAt] = useState({ left: request.x, top: request.y })
  useLayoutEffect(() => {
    const menu = box.current
    const area = menu?.offsetParent as HTMLElement | null
    if (!menu || !area) return
    const fit = (x: number, size: number, room: number) => Math.max(0, Math.min(x, room - size))
    setAt({ left: fit(request.x, menu.offsetWidth, area.clientWidth), top: fit(request.y, menu.offsetHeight, area.clientHeight) })
  }, [request])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    const onDown = (event: PointerEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) onClose()
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('pointerdown', onDown)
    box.current?.querySelector('button')?.focus()
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('pointerdown', onDown)
    }
  }, [onClose])

  const { title, items } = itemsFor(request, disturb)
  return (
    <div
      ref={box}
      role="menu"
      aria-label={`Disturb ${title}`}
      data-testid="disturbance-menu"
      className="bg-popover text-popover-foreground absolute z-[1000] min-w-56 rounded-md border p-1 text-sm shadow-md"
      style={at}
    >
      <div className="text-muted-foreground px-2 py-1 text-xs font-medium">Disturb {title}</div>
      {items.length === 0 && <div className="text-muted-foreground px-2 py-1 text-xs">Nothing to disturb here.</div>}
      {items.map((item) => (
        <button
          key={item.label}
          type="button"
          role="menuitem"
          title={item.hint}
          className="hover:bg-accent focus:bg-accent block w-full rounded px-2 py-1 text-left outline-none"
          onClick={() => {
            item.run()
            onClose()
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
