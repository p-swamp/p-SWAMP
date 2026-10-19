import { useCallback, useEffect, useRef, useState } from 'react'

import type { Wire } from '@/api/wire'
import { CommandError, postCommand } from '@/lib/commands'
import { CIM_GRAPH_API_PATH, CIM_GRAPH_WS_PATH, resolveApiUrl } from '@/lib/servers'
import { useServerSocket } from '@/hooks/useServerSocket'

/** What the server pushes, and the static layout, both generated from the api contract: the models
 *  declared in app/server-python/src/cim_graph/model.py, not hand-copies of them. */
export type CimGraphState = Wire['CimGraphState']
export type CimLayout = Wire['CimLayout']

/** Where the graph is: being loaded into its store, there, there but read-only, or not to be had. */
export type GraphStatus =
  | { kind: 'loading' }
  | { kind: 'ready' }
  | { kind: 'read-only' }
  | { kind: 'unavailable'; reason: string }

/** A command on its way: what it asked for, and when, until the socket shows it done. */
type Pending = { want: boolean; line: boolean; sent: number }

const LOADING_RETRY_MS = 1000
/** A command whose result has not shown by then is given up on: the state on screen is the truth. */
const PENDING_TIMEOUT_MS = 15_000

/**
 * The CIM graph app: the layout is fetched once (again every second while the server is still loading
 * the grid), the state (which switches are open, which branches are out of service) arrives on the
 * socket, and commands go up as POSTs to /api/cim-graph.
 *
 * The graph is shared: whatever any visitor does shows here. A command is `pending` (by the mRID it
 * names) from the click until the socket shows its result, which is when its round trip is measured;
 * one that is refused (an unknown id, a state it is already in, a graph that is read-only) sets `error`
 * to the server's reason and is no longer pending.
 */
export function useCimGraphSocket() {
  const { message, status, connected } = useServerSocket<CimGraphState>(CIM_GRAPH_WS_PATH)
  const [layout, setLayout] = useState<CimLayout | null>(null)
  const [unavailable, setUnavailable] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<ReadonlyMap<string, Pending>>(new Map())
  const pendingNow = useRef<ReadonlyMap<string, Pending>>(pending)
  const [roundTripMs, setRoundTripMs] = useState<number | null>(null)
  const [changedAt, setChangedAt] = useState<Date | null>(null)
  const previous = useRef<CimGraphState | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let retry: ReturnType<typeof setTimeout> | null = null
    const fetchLayout = () =>
      fetch(resolveApiUrl(`${CIM_GRAPH_API_PATH}/layout`), { signal: controller.signal })
        .then(async (r) => {
          if (r.ok) return (await r.json()) as CimLayout
          const detail = ((await r.json().catch(() => ({}))) as { detail?: string }).detail ?? String(r.status)
          if (r.status === 503 && detail === 'the grid is loading') {
            retry = setTimeout(fetchLayout, LOADING_RETRY_MS)
            return null
          }
          throw new Error(detail)
        })
        .then((body) => {
          if (body && !controller.signal.aborted) setLayout(body)
        })
        .catch((e: Error) => {
          if (!controller.signal.aborted) setUnavailable(e.message)
        })
    void fetchLayout()
    return () => {
      controller.abort()
      if (retry) clearTimeout(retry)
    }
  }, [])

  // Every new state: the time of the change, and the commands it shows done (with their round trip).
  useEffect(() => {
    if (!message || message === previous.current) return
    if (previous.current) setChangedAt(new Date())
    previous.current = message
    const out = new Set(message.out_of_service)
    const now = performance.now()
    const still = new Map<string, Pending>()
    let trip: number | null = null
    for (const [mrid, p] of pendingNow.current) {
      const done = p.line ? out.has(mrid) === p.want : message.switches[mrid] === p.want
      if (done) trip = Math.round(now - p.sent)
      else if (now - p.sent < PENDING_TIMEOUT_MS) still.set(mrid, p)
    }
    pendingNow.current = still
    setPending(still)
    if (trip !== null) setRoundTripMs(trip)
  }, [message])

  const send = useCallback((mrid: string, p: Pending, command: () => Promise<void>) => {
    setError(null)
    pendingNow.current = new Map(pendingNow.current).set(mrid, p)
    setPending(pendingNow.current)
    command().catch((e: unknown) => {
      console.error('cim-graph command failed', e)
      setError(e instanceof CommandError ? e.detail : String(e))
      const still = new Map(pendingNow.current)
      still.delete(mrid)
      pendingNow.current = still
      setPending(still)
    })
  }, [])

  const setSwitch = useCallback(
    (mrid: string, open: boolean) =>
      send(mrid, { want: open, line: false, sent: performance.now() }, () =>
        postCommand(`${CIM_GRAPH_API_PATH}/switches/{mrid}`, { path: { mrid }, body: { open } }),
      ),
    [send],
  )
  const setLine = useCallback(
    (mrid: string, open: boolean) =>
      send(mrid, { want: open, line: true, sent: performance.now() }, () =>
        postCommand(`${CIM_GRAPH_API_PATH}/lines/{mrid}`, { path: { mrid }, body: { open } }),
      ),
    [send],
  )
  const reset = useCallback(() => {
    setError(null)
    postCommand(`${CIM_GRAPH_API_PATH}/reset`).catch((e: unknown) => {
      console.error('cim-graph reset failed', e)
      setError(e instanceof CommandError ? e.detail : String(e))
    })
  }, [])

  const graph: GraphStatus = unavailable
    ? { kind: 'unavailable', reason: unavailable }
    : !layout || !message
      ? { kind: 'loading' }
      : message.writable
        ? { kind: 'ready' }
        : { kind: 'read-only' }

  return {
    state: message,
    layout,
    status,
    connected,
    graph,
    error,
    pending,
    roundTripMs,
    changedAt,
    setSwitch,
    setLine,
    reset,
  }
}
