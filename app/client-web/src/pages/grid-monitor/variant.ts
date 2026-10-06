/**
 * How a panel is being rendered.
 *
 * `dashboard` is the main window on `/`, where a panel is a dock: compact, sized
 * by the window, and offering a link to its own route. `focused` is that route:
 * the same component, given more room and its full set of controls. One
 * component serving both is what keeps the two from drifting apart.
 */
export type PanelVariant = 'dashboard' | 'focused'

/**
 * Table density per variant. A dock's table is a Qt table widget's: small type,
 * tight rows, as many of them visible as the dock has room for. Focused, the
 * shared table's own spacing stands.
 *
 * Descendant selectors rather than classes on each cell, so one string on the
 * `<Table>` restyles all of it — and outranks the padding the cells set on
 * themselves.
 */
export function tableDensity(variant: PanelVariant): string | undefined {
  return variant === 'dashboard'
    ? 'text-xs [&_td]:px-2.5 [&_td]:py-1 [&_th]:h-7 [&_th]:px-2.5'
    : undefined
}
