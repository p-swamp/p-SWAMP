# Writing the state estimate to the SV profile

**Not done yet.** Today the estimate is only a message on the transport (`StateEstimatorResult`).
This note says how the CIM graph's SV profile (`cgmes:model:SV`) could follow it, without disturbing
the other readers of the graph. These notes come from reading the code at the time of writing.

## Why a plain write to SV would not do

**The write itself is cheap.**
- Nordic44's SV file has about 2,650 objects, or about 10k triples: 1,184 `SvPowerFlow`,
  951 `SvStatus`, 240 `SvVoltage`, 165 `SvSwitch`, 47 `TopologicalIsland`, 36 `SvTapStep` and
  24 `SvShuntCompensatorSections`.
- An estimate needs only `SvVoltage` plus the injection `SvPowerFlow`s, about 2–3k triples.
- That is one SPARQL update, the same size and kind as the SCADA scan, which `Store.put_measurements`
  replaces every 2 s.

**The version stamp is the problem.**
- The graph has one change counter, `<urn:pswamp:cim> <urn:pswamp:version>` in `urn:pswamp:meta`,
  and every edit bumps it.
- A reader that sees the counter move cannot tell what changed. `refresh_expired`
  (`core/src/pswamp_core/cim/store.py`) therefore expires both SSH and SV.
- Expiring SV costs the live simulation nothing. Its export (`rtsim_from_cim.engine.EXPORT`) does not
  set `voltage_fallback="sv"`, so it never loads an SV object.
- Expiring SSH does cost something. Every SSH field the export holds is re-read: switch states,
  terminal connections, load and machine set-points and tap positions. This takes a few batched
  queries, and then the tables are rebuilt and compared. LiveTops rebuilds nothing when nothing
  differs, but the reads are wasted work.
- With an estimate every 10 s, the simulation's controller would do that every 10 s, and so would
  every `cim = True` module, through `GraphWatch`.
- Writing SV without bumping the counter is no better: no reader would ever notice the new values.

## The proposal: SV gets a counter of its own

This is the same pattern as the SCADA values (`urn:pswamp:measurements` with its `_SCAN_BUMP`,
ADR-017).

1. **The core (`pswamp_core.cim.store`).** Add `Store.put_state(graph)`:
   - Clear what the estimate owns in `cgmes:model:SV` and insert the new values, in one update.
   - Bump `<urn:pswamp:cim> <urn:pswamp:sv>` in `urn:pswamp:meta`, never `<urn:pswamp:version>`.
   - Give a reader a way to watch that counter, such as `SvVersion(store).changed()`, beside
     `GraphVersion`. A reader that sees it move expires only `profile="SV"`.
   - Decide what a reset does with the estimate. `reset` writes SSH back today; it could also clear
     the estimated SV, or leave the last estimate in place.
2. **The writer (`app/server-python/src/cim_graph/grid.py`).** Add `Writer.write_estimate`:
   - The CIM graph app subscribes to `StateEstimatorResult` and writes it, as it does with `ScadaScan`.
   - It stays the one writer of the graph. The module never commits.
   - A rate cap there (say, at most one write per 10 s) keeps the store's load independent of the
     module's `period`.
3. **Readers that want the estimate** (contingency analysis, say) watch the SV counter. They can also
   read the message directly and skip the graph.

## Mapping the message to SV

- **`SvVoltage` is per `TopologicalNode`, but the estimate is per station (voltage level).** Write the
  station's `v` (kV) and `angle` (degrees) to every TopologicalNode of that voltage level that is
  energised. A voltage level split by an open bus coupler has several TopologicalNodes. A per-station
  estimate cannot tell them apart; a per-node estimate would be needed for that.
- **The angle needs a reference.** The message carries the PMU angles as measured. SV angles are
  usually relative to the island's slack or reference bus. Pick a reference station per
  `TopologicalIsland` and subtract its angle before writing.
- **`SvPowerFlow` is per `Terminal`, and positive *into* the equipment** (a load positive, a generator
  negative). `BusEstimate.p_mw`/`q_mvar` is a station's *net* injection into the branches, the other
  way round. Splitting it among the station's machines and loads needs their measurements: the SCADA
  `P`/`Q` Analogs in the graph's OP profile, or an estimator that estimates per equipment.
- **What the estimator does not own stays as it is:** `SvStatus`, `SvSwitch`, `SvTapStep`,
  `SvShuntCompensatorSections` and `TopologicalIsland`. Topology processing would own those. The
  update deletes and inserts only `SvVoltage` and the `SvPowerFlow`s the estimate gives.
- **Timestamp.** CGMES SV has no timestamp per value. The scenario time belongs in the model header
  (`md:Model.scenarioTime`) of the SV graph. Set it to the estimate's `timestamp` in the same update.

## What it does not change

- The live simulation does not read SV, so an estimate written there never feeds back into it.
- The message stays. It is what the writer writes from, and the direct feed for consumers that do not
  want to query the graph.
