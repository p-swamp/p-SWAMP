# ADR-014: Keep the CIM graph in one Oxigraph store, with one writer, readable by every module

- Status: Proposed
- Date: 2026-10-15

## Context

[ADR-013](013-put-a-cim-reference-id-on-each-frame.md) put a CIM reference id on each frame and left
the lookup it names for later: a module that needs grid data must resolve the id itself, and nothing
to do that was built. This is that lookup, and the store it reads.

The live grid simulation (`modules/rtsim-from-cim/`) used to read a CIM grid once into private
dataclasses, convert them to a TOPS model, and take a line out of service through a command routed to
the source. The grid was a private in-process copy: nothing else could see it or change it, and the
source needed a command path of its own.

We want the opposite. The CIM graph should be *the* copy of the grid, one that the simulation, a web
page and a person with a SPARQL client all see, and that is steered by editing it: opening a breaker
changes the simulated grid. We also want the lowest latency from a change in the graph to the
simulation, and the graph to be part of every module's baseline data: a PMU frame should say which
element of the grid each column measures, not only `cimReferenceId = "n44-cim-stub"`.

LazyCIM 0.2 makes that practical: named graphs per CGMES profile, cache policies per profile, a SPARQL
backend whose commit is one update, and a TOPS exporter that keeps every switch as a branch, exports
the controllers and refreshes its model from what its cache policy expired. A version stamp,
written with every edit, says when to look.

## Decision

**One store, Oxigraph** (`PSWAMP_CIM_URL`), in memory, with no volume, queried with plain SPARQL 1.1
(queries at `/query`, updates at `/update`, `--union-default-graph`). Each CGMES profile is a named
graph, `cgmes:model:<KW>`, and each vocabulary `cgmes:schema:<KW>`. With no URL, each process has an
in-process store with the same graphs and the same SPARQL (`pswamp_core.cim.LocalStore`).

**One writer: the web backend's CIM graph app** (`app/server-python/src/cim_graph/grid.py`). It fills
the empty store when the server starts. Before that, it completes the grid in a private copy: the
machines get dynamics, and every place a PMU can observe gets an `Analog` in the Operation profile. It
then edits the store: one commit, one SPARQL update. Nothing else commits, and a layering test holds
that. Because the graph changes only when the app writes, the page needs no poller: after each write
the app pushes the state read from its own repository.

**Many readers, each through a repository of its own** (`pswamp_core.cim.connect_reader`). A reader
refuses to commit, and keeps what it read for ever. A **version stamp** tells it when to read again:
the writer appends a bump of one triple (`urn:pswamp:cim urn:pswamp:version`, in `urn:pswamp:meta`) to
the same SPARQL update as every edit, so no reader sees the edit without the stamp. A reader that wants
to know asks for the stamp (one tiny query, `GraphVersion.changed()`) and, when it moved, expires the
profiles that change (SSH, SV) so its next read sees the edit. Nothing is re-read on a timer.

**A module reads the graph through its host** (`cim = True`, then `self.cim_repo`, connected before
`setup`). It gets one repository per instance, because a LazyCIM repository is not thread-safe.
**The core keeps that repository up to date, not the module.** One watch per store and process
(`pswamp_core.cim.GraphWatch`) asks for the stamp every 0.2 s (`PSWAMP_CIM_POLL`) in a thread of its
own and counts the changes; before each input or command, an instance whose count is behind has its
repository's SSH and SV expired, under its lock, and is told (`Module.cim_changed()`), so it can
rebuild whatever it derived from the graph. The check before a call compares two integers and reads
nothing.

**PMU data stays `PmuFrame`, tied to the graph.** `PmuHeader.analog` holds each column's Analog mRID,
and `cimReferenceId` is the grid's model id. The two columns of a phasor share one Analog. The Analogs
are named by one rule, `PMU_<substation>_<kV>_<V|F|I>[_<line>]`. A pipeline file's
`[enrich] cim = true` matches each column to its Analog by that rule, once per layout. A source that
knows the graph, like the simulation, sets the links itself. Grid data itself still never travels
on a frame (ADR-013): the links are mRIDs, and a module reads what they point at.

**A script may bring its own store.** A script, unlike a deployment, often already holds a grid (a
LazyCIM demo model in an embedded Oxigraph, a GraphDB repository) and should not have to copy it into
ours to try a module on it. It hands a module its repository (`module.cim_repo = repo`), over any
LazyCIM backend, or names a backend in `CimSettings(backend=..., shared=...)`: a callable that makes
it, which must pickle, so a reader in a child process opens its own. First match wins: a repository
handed over, then `backend`, then `PSWAMP_CIM_URL`, then the in-process store. Such a store is only
read (`Store.owned`): never filled, reset or stamped. `pswamp_core.cim.prepare(repo)` gives its grid
dynamics and PMU Analogs once, writing to that store only; it is the one other writer the layering
test allows. Having no stamp, such a store is treated as changed every 2 s
(`GraphVersion(unstamped_every=...)`), and a reader re-reads the profiles that change that often;
once a stamp appears it follows that instead.

**The simulation is LazyCIM's TOPS export, followed by `refresh()`.** The export has every switch as a
branch, open switches tripped after the load flow, a PLL per bus, and the machines' controllers.
Because the buses never change, a switch is a `Line.event` on its own row and keeps its transient,
couplers included. A load's P and Q move its admittance. Rows that come or go mean starting over from
the new model. The follower looks at the version stamp every `POLL` (0.2 s) and, only when it moved, expires SSH and SV
and calls `refresh()`; idle, it reads nothing but the stamp. Over Oxigraph it does so in a process of
its own, so a refresh (a second or so of Python) never holds up the frames to the pages. The model is
stepped and paced in a process of its own too, at 50 frames a second.

## Consequences

- An edit reads nothing and is one update (measured: 0 queries, 1 update). The page shows it as soon
  as the update returns. The simulation applies it after one refresh, before its next step: about
  0.25 s after the edit, and with no polling of the graph.
- A PMU value reaches the grid in one call: `self.cim_repo.from_mRID(frame.header.analog[i])`.
- A module carries no refresh code, and cannot forget it. The store is asked for the stamp once per
  process every 0.2 s, however many modules read it and however fast their inputs come; an edit
  reaches a module at its first call after the next poll.
- Couplers and transformers (through their bay breakers) are followed. Governors, exciters and
  stabilisers are simulated where the graph has them; Nordic44's dynamics have none, so its frequency
  is still not regulated after a disturbance.
- An edit made straight in the store, bypassing the app, reaches the simulation (its reader expires)
  but not the page, which only shows what the app wrote. That is the single-writer rule: don't edit the
  store by hand.
- Oxigraph is open source (MIT/Apache-2.0), and only SPARQL 1.1 is used, so another store can stand in.
- The stack's "nothing is persisted" rule holds, but there is now a store *process* that other processes
  read: it has no volume, and the server loads the grid into it when it starts, so a restart puts every
  edit back.
- The in-process store is rdflib: correct, but slow for big reads. It serves tests, scripts and a
  server alone; a deployment sets `PSWAMP_CIM_URL`.
- The recorded PMU data names its stations by the TOPS Nordic44 bus numbers, which do not map
  one-to-one onto the CIM Nordic44's substations. Its columns carry no Analog until a station alias
  table (`PSWAMP_CIM_STATIONS`) is given.
- The graph is still shared and unauthenticated: narrow CORS and add authentication before this
  serves anyone who should not drive the grid.
- An edit to a script's own store is seen within the polling interval (2 s), not at once.

## Alternatives considered

- **A private in-process copy per reader**, as the simulation first had: nothing else could see or
  steer that grid, and each reader would need a command path of its own.
- **Re-reading on a timer** (a TTL per profile): either stale or wasteful; the stamp costs one tiny
  query and reads nothing when nothing changed.
- **Each module looking at the stamp itself**, before its calls: no thread, but one query per
  instance at stream rate, on the event loop for a module that is not `blocking`, and code every
  module has to carry.
- **Several writers**: every page and source editing the store would need to agree on what was
  written; one writer that pushes what it wrote needs no poller and no reconciliation.
- **For a script's store, a repository only** (it cannot cross into a child process, so a reader of a
  shared store could not run apart), **a factory only** (every script would build a backend it already
  has), or **URL schemes in `PSWAMP_CIM_URL`** (a closed list in the core, options squeezed into a
  URL).
