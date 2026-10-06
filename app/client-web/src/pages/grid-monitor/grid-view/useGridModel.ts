import { useEffect, useState } from 'react'

import { GRID_MODEL_PATH, resolveApiUrl } from '@/lib/servers'

import type { GridModel } from './scene'

// The topology is static for the life of the server, so it is fetched once per
// page load however many views ask for it. A failed fetch is forgotten, so the
// next view to mount tries again rather than inheriting the failure.
let pending: Promise<GridModel> | null = null

function loadGridModel(): Promise<GridModel> {
  pending ??= fetch(resolveApiUrl(GRID_MODEL_PATH))
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then((body) => body as GridModel)
    .catch((error) => {
      pending = null
      throw error
    })
  return pending
}

/** The grid model, or null until it has loaded; `failed` once it could not be. */
export function useGridModel(): { model: GridModel | null; failed: boolean } {
  const [state, setState] = useState<{ model: GridModel | null; failed: boolean }>({
    model: null,
    failed: false,
  })

  useEffect(() => {
    let live = true
    loadGridModel().then(
      (model) => live && setState({ model, failed: false }),
      () => live && setState({ model: null, failed: true }),
    )
    return () => {
      live = false
    }
  }, [])

  return state
}
