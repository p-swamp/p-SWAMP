const COLORS = ['#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#65a30d', '#0284c7', '#b45309', '#4f46e5', '#be123c']

/** The colour of station `i`, the same on both charts and in the station list. */
export const stationColor = (i: number) => COLORS[i % COLORS.length]
