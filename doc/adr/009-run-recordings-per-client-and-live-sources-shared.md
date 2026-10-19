# ADR-009: Give each client its own run of a recording, and share one run per live source

- Status: Accepted
- Date: 2026-10-19

> Written up after it was built, from PR #13. The date is when that pull
> request merged.

## Context

Today the web stack explores recorded PMU data; later it will also show a live
feed. Someone opening a recording wants the event from the start, at their own
speed, not someone else's replay already half way through. The grid monitor
learned this when it moved off its single `HUB` for the whole process. A live
feed needs the opposite: everyone watching must see the same instant, and its
analysis should run once, however many people watch. Modules keep state (an
excursion count, a window), so which module instance a frame reaches decides
what a viewer sees.

## Decision

We will key every pipeline run, and every record it publishes, by who it
belongs to:

- A recording gets **one run per client** (a browser, by its client id), with
  its own cursor and speed, and **one module instance per run**.
- A live source gets **one run, always on**, keyed `live.<source>`, started
  with the app. A client that switches to it follows that run's topics and
  opens no stream of its own.
- A record's key is the run key, a run id and a stream number
  (`42#1760512345678.3`, `core/src/pswamp_core/keys.py`). A host gives a new
  run a fresh module instance, and resets it when the stream starts over (a
  seek, a switch, a loop).
- While a client follows a live run, a command for a module that reads the
  stream is refused with a 409, because that instance belongs to every viewer.

## Consequences

- What a recording shows does not depend on who else is watching. A run
  outlives its sockets by five minutes, so a reload rejoins it.
- Each run costs a module instance per module, plus the memory and threads that
  come with them. `PipelineRegistry` therefore caps runs at 8. At the cap it
  evicts the least recently used idle run, and refuses a new client if every run
  is watched.
- Live analysis runs with no viewer, as it would in a control room.
- Runs live in the server's memory, so the server runs one replica: a client's
  sockets landing on two pods would be two unrelated runs.
- A per-viewer setting on a live module is not possible: it would change what
  everyone sees.

## Alternatives considered

- **One shared run per app**, as the grid monitor first had. Cheapest, but every
  visitor lands in someone else's replay, and one viewer's seek moves everyone.
- **A private run of a live source for each viewer.** Each viewer could set
  their own module options, but the same analysis would run once per viewer, and
  viewers could disagree about the present.
- **A run per window or per socket.** A person with two windows, or one page
  with five sockets, would see several replays. The id is per browser profile:
  a person, not a window (`app/client-web/src/lib/clientId.ts`).
