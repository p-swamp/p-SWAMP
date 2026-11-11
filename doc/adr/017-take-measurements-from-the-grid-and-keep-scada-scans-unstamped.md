# ADR-017: Take the measurements from the grid's Operation profile, and keep SCADA scans beside the graph's version

- Status: Proposed
- Date: 2026-11-06

## Context

[ADR-016](016-command-the-live-simulation-and-let-it-report-cim-edits.md) made everything observable a
measurement: the page and any detection module see the simulated grid only through `PmuFrame` columns
tied to CIM Analogs. Those Analogs were p-SWAMP's own: the core generated one per place a PMU could
observe (`PMU_<substation>_<kV>_<V|F|I|P|Q>`), one Analog per phasor, whatever grid it loaded.

A grid can bring its own measurements. CGMES keeps them in the Operation profile: `Analog`s and
`Discrete`s with a `measurementType`, units, a `Terminal` and a `PowerSystemResource`, and values
(`AnalogValue`, `DiscreteValue`) tied to a `MeasurementValueSource`. The Nordic44 a user runs here has
one, with 1102 Analogs and 55 Discretes from two sources, `PMU` and `SCADA`: PMU voltage magnitude and
angle, frequency and ROCOF per busbar, current magnitude and angle per branch end; SCADA active and
reactive power per branch end, machine and load, a voltage per busbar, and a position per switch. Its
PMUs measure no power. Ignoring that profile meant a frame's Analogs were not the grid's, and the
power of machines and loads came from PMUs the grid does not have.

SCADA is a second kind of measurement, slower and different: every couple of seconds, a scan of power
flows, voltages and switch positions. Operators and state estimators read it; a topology-detection
module will compare its switch positions with the graph.

## Decision

**We will take the measurements from the grid's Operation profile when it has them.** A measurement
is p-SWAMP's when a value of it comes from the `PMU` or the `SCADA` source; such a grid gets nothing
added, and its mRIDs are what frames and scans point at. A grid with none (the committed sample grid,
stock Nordic44) is given them when it is loaded, by the same conventions: standard CGMES
`measurementType`s, a magnitude and its angle as two Analogs, `unitSymbol` and `unitMultiplier`,
`phases`, `positiveFlowIn`, the two sources, and names `PMU_<where>_<what>` and
`SCADA_<where>_<what>`. One reader, `pswamp_core.cim.measurement_table`, lists them for every user.

**We will stream the grid's PMUs.** The live simulation's frames have one column per PMU measurement,
each carrying its own Analog: a voltage's magnitude and angle, a frequency and its rate of change, a
current's magnitude and angle at a branch end, and power only where the grid's PMUs measure it.

**We will publish SCADA scans as messages.** Every `RTSIM_SCADA_PERIOD` seconds of its clock (2 by
default), the simulation scans every SCADA measurement of the graph and publishes a `ScadaScan`: one
value per Analog and Discrete, in the units and with the sign the measurement declares (a flow into
the equipment is positive, so a generator's power is negative). A part of the grid the simulation
left out reports nothing.

**We will keep the latest scan in the graph, but not as an edit.** The graph's one writer (ADR-014)
writes each scan's values as `AnalogValue`s and `DiscreteValue`s from the `SCADA` source into a graph
of their own, `urn:pswamp:measurements`, replacing the previous scan in one update. That update does
not move the version stamp; it moves a counter of its own (`<urn:pswamp:measurements>
<urn:pswamp:scan>` in `urn:pswamp:meta`). A reset empties the graph.

## Consequences

- The ids in frames changed: a phasor's magnitude and angle are two Analogs, and on the sample grid and
  Nordic44 the simulation's frames carry no power. Machine and load power, and the page's generation
  and load totals, come from SCADA.
- A reader that follows the version stamp (the simulation's controller, every module's repository)
  never reads the steady-state hypothesis again because of a scan. A reader that wants the latest
  values asks for them: the graph of latest values, or the scans themselves on the transport.
- The graph now knows two states of a switch: its `Switch.open`, which only reported operations
  change (ADR-016), and its latest scanned position, which follows the simulation within a scan. They
  can disagree, after a disturbance protection did not report or between two scans; the grid page
  marks a breaker where they do.
- The grid's static `AnalogValue.value`s (a profile's snapshot) stay in the Operation profile; the
  latest scanned values are other objects, in the measurements graph, stamped with their time. Over
  the in-process store, which reads every graph merged, a query for a measurement's values sees both.
- A real SCADA feed would publish the same `ScadaScan`; the writer does not care who scanned.

## Alternatives considered

- **Keep generating our own Analogs for every grid**: frames would not point at the grid's own
  measurements, and a grid's PMUs that measure no power would be given some.
- **Write the latest values into the Operation profile, as edits**: every scan would move the stamp,
  and every reader would read SSH and SV again every two seconds for nothing.
- **Keep the latest scan only in memory, in the web backend**: modules reading the graph could not see
  what SCADA says, which is what a state estimator or a topology check needs.
- **SCADA as more `PmuFrame` columns**: a frame is 50 a second and its header is fixed; a scan is
  every couple of seconds, and a measurement left out must be able to have no value.
