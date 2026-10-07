/**
 * One number per station, from a source that changes too often to be a prop.
 *
 * The grid view takes its samples this way round — it subscribes, and reads
 * when told to — so that a stream ticking ten times a second reaches the canvas
 * without a React render in between.
 */
export type LiveValues = {
  subscribe: (notify: () => void) => () => void
  /** Station name to value, for the stations that have one. */
  read: () => Map<string, number>
}

/** A `LiveValues` that something else writes into. */
export type LiveValueStore = LiveValues & {
  set: (values: Map<string, number>) => void
}

export function createLiveValues(): LiveValueStore {
  let current = new Map<string, number>()
  const listeners = new Set<() => void>()
  return {
    subscribe(notify) {
      listeners.add(notify)
      return () => {
        listeners.delete(notify)
      }
    },
    read: () => current,
    set(values) {
      current = values
      listeners.forEach((notify) => notify())
    },
  }
}
