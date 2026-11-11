# ADR-016: Command the live simulation, and let it report what it did to the CIM graph

- Status: Proposed
- Date: 2026-11-03

## Context

[ADR-014](014-keep-the-cim-graph-in-one-oxigraph-store-with-one-writer.md) made the CIM graph the one
copy of the grid. The live simulation is steered by editing that graph: opening a breaker on the
grid page writes `Switch.open`, and the simulation follows the version stamp.

That makes the graph say what *should* be, not what *is*. In a real grid the two differ:

- An operator commands a breaker, and the breaker opens or does not. The state that reaches the
  control room is the breaker's, reported after the fact.
- A line trip or a fault is not commanded at all. Nothing writes it anywhere; it shows only in the
  measurements, and the topology has to be inferred from them.

p-SWAMP is meant to explore exactly that gap. A topology-detection module, to come, will read PMU
frames and propose what the graph should say. The simulation therefore has to be the ground truth,
and the graph only what is known.

## Decision

**We will command the live simulation, not the graph.** An operation (opening or closing a breaker,
or the terminal of a line that has none) is a command addressed to the live source,
`rtsim-from-cim`. The core gains commands addressed to a live source. As every command
([ADR-010](010-address-commands-by-class-acknowledge-on-acceptance.md)), each command class has one
receiver, and is acknowledged on acceptance. It goes to the source's shared run (`live.<source>`,
[ADR-009](009-run-recordings-per-client-and-live-sources-shared.md)). With no simulation running, an
operation is refused.

**We will let the simulation report what it did, as CIM edits.** When a switch in the simulation has
opened or closed, the source publishes a `CimEdits` message: a list of `(mRID, attribute, value)`
with its producer, cause and simulated time. This covers a switch opened by a command and one opened
by the simulation's own protection. The `cim_graph` app subscribes to it, writes the edits and
pushes its state. It stays the graph's only writer, applying the edits each producer is allowed:
`Switch.open` and `ACDCTerminal.connected` for the simulation.

**We will inject disturbances into the simulation only.** A line trip or reconnection, a bus short
circuit, or a load step is a command too, but its effect is never written to the graph. It shows in
the measurements alone, and the source announces it as a `SimEvent`.

**We will keep following the graph.** A direct edit of the graph still reaches the simulation, as in
ADR-014: a reset, a load, a setpoint, or a switch edited by hand. A switch reported by the
simulation and then written comes back to it as a change it has already made, which TOPS's
idempotent events turn into nothing. A reset also restarts the simulation from the graph, clearing
every disturbance.

**Everything observable is a measurement.** What the page shows of the simulated grid (voltages,
frequencies, currents, loading, the power of machines and loads) reaches it as `PmuFrame` columns
tied to CIM Analogs. A detection module therefore sees exactly what an operator sees.

This decision changes ADR-014 in one place. The graph is no longer how the simulation is *steered*;
it is what is *known* about the grid. ADR-014's one store and one writer stand.

## Consequences

- An operation now makes a round trip through the simulation before the page shows it: command,
  TOPS event, report, write, push. The graph never shows a breaker state the simulation did not
  reach.
- The graph and the simulation can disagree, on purpose. After a line trip the graph still has the
  line in service. Telling the two apart is what the topology-detection module is for.
- A live source now has commands. The rule "a command for a module that reads the stream is
  refused while following" does not apply, since the source is not such a module. A command
  reaches the one simulation every viewer shares, as an edit of the shared graph already did.
- The writer applies edits that another process proposed, so its allow-list is what keeps the
  graph's one-writer rule meaningful. A new producer (the detection module) needs an entry there.
- Without a simulation (a deployment that runs no `rtsim-from-cim`), breakers cannot be operated
  from the page. The graph can still be edited by hand or reset.

## Alternatives considered

- **Keep steering by the graph** (ADR-014 as it was): the graph could never be wrong, so there would
  be nothing to detect.
- **Let the simulation write the graph itself**: a second writer. The page, which pushes only what
  its writer wrote, would go stale, and two writers would need to agree on what was written.
- **A message per kind (`SwitchOperated`)** instead of generic CIM edits: simpler at first, but the
  detection module would need a message of its own for the same purpose.
- **Write every change the simulation makes, line trips included**: the graph would be the ground
  truth again, and detection pointless.
