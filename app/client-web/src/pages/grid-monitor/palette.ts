/**
 * Colours carried over from the Qt front end, so the two read the same.
 *
 * Every plot there -- the grid view, the frequency trace, the phasor diagram --
 * sits on one dark teal, and the island palette was chosen against it. Both are
 * `src/pswamp/styles/colors.py`, verbatim, which is why the plots here keep that
 * background in light and dark mode alike: the palette only works on it.
 */

/** `colors.background`: the canvas of every plot. */
export const PLOT_BACKGROUND = '#1e3f40'

/** The default trace colour of a Qt plot (`TimeSeriesPlot.add_plot`). */
export const TRACE_COLOR = '#d3d3d3'

/**
 * `colors.islanding`. Index 0 is the main system and is deliberately neutral: it
 * is the *absence* of a split, so it recedes while a genuine island stands out.
 *
 * One definition, shared by every view that draws islands -- the grid view, the
 * phasor diagram and the frequency traces sit side by side, and an island must
 * be the same colour in all three. The Qt list repeats its blue at index 5; that
 * repeat is dropped here, since two islands sharing a colour helps nobody.
 */
export const ISLAND_COLORS = [
  '#bababa',
  '#4876ff',
  '#089200',
  '#42e3d6',
  '#ff5050',
  '#caff70',
  '#ff83fa',
  '#65ccff',
]

/** The colour for an island index, wrapping if the detector reports more
 *  groups than there are colours. */
export function islandColor(index: number | null | undefined): string {
  return ISLAND_COLORS[(index ?? 0) % ISLAND_COLORS.length]
}

/** What the Qt views call the groups: index 0 is the grid itself. */
export function islandName(index: number): string {
  return index === 0 ? 'System' : `Island ${index}`
}
