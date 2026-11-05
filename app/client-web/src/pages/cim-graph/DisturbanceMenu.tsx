import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { disturbancesOf } from './disturbances'
import type { Disturb } from './disturbances'
import type { MenuRequest } from './GridMap'

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

  const { title, items } = disturbancesOf(request.target, disturb)
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
