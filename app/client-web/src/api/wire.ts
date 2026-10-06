/**
 * The api contract, as the rest of the client sees it.
 *
 * `schema.ts` beside this file is GENERATED from `doc/api/openapi.json`, which is
 * itself generated from the server (see `uv run pswamp api generate`). This
 * file is the small hand-written layer over it, so no page has to know the shape
 * of a generated module.
 *
 * `Wire[...]` is every model the server publishes, including the WebSocket
 * message shapes — those reach the document through the `x-websocket-channels`
 * extension, since OpenAPI itself has no notion of a socket. So a page hook says:
 *
 *     type PmuStreamState = Wire['PmuStreamState']
 *
 * instead of hand-copying the Python model's fields into TypeScript and hoping
 * the two stay in step. The field names stay snake_case, as the server sends
 * them, all the way to the components: a hook that renamed them into a camelCase
 * mirror would have to be edited for every new field, and forgetting one is not
 * a type error — the field would simply never appear.
 *
 * Don't edit `schema.ts`. Change the Python model, run
 * `uv run pswamp api generate`, and commit both artifacts — until you do,
 * `uv run pswamp check` fails.
 */
import type { components, paths } from './schema'

/** Every model in the contract, keyed by name. */
export type Wire = components['schemas']

/** Every path in the contract, keyed by url. Used to type `postCommand`. */
export type ApiPaths = paths
