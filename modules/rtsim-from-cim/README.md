# rtsim-from-cim

`pswamp-rtsim-from-cim`, package `pswamp_modules.rtsim_from_cim`, class
`RtsimFromCimSource`, entry point `rtsim-from-cim` (group `pswamp.modules`).

A **live source**: a TOPS dynamic simulation of the grid in the **CIM graph**, run in real time.
The graph is the one copy of what is *known* of the grid (`pswamp_core.cim`, ADR-014); the
simulation is what *is* (ADR-016). It is steered by **commands**, and it also follows the graph:
whoever edits the graph (the web backend's CIM graph app, its only writer) steers it too. Not
playable: a run follows the source as it goes.

| | Message | Topic | Defined in |
|---|---|---|---|
| Reads | nothing on the transport (the CIM graph, through its own repository: `cim = True`) | | |
| Emits | `PmuFrame` (mRID `rtsim-from-cim`): one column per PMU measurement of the graph, each column carrying its own Analog (`header.analog`) | `pmu.frame` | `pswamp_models.pmu` |
| Emits | `ScadaScan` (source `rtsim-from-cim`): every `SCADA_PERIOD` s of its clock, the value of every SCADA measurement of the graph, for the graph's one writer to keep as the latest (ADR-017) | `scada.scan` | `pswamp_models.scada` |
| Emits | `SimEvent`: every command applied, announced at once | `sim.event` | `pswamp_models.rtsim` |
| Emits | `CimEdits` (producer `rtsim`): an operation, once the engine applied it, for the graph's one writer | `cim.edits` | `pswamp_models.cim` |
| Accepts | `OperateSwitchCommand`, `OperateLineCommand` (operations); `TripBranchCommand`, `ReconnectBranchCommand`, `ShortCircuitCommand`, `ClearShortCircuitCommand`, `FaultAndClearCommand`, `LoadStepCommand` (disturbances); `ResetSimulationCommand` | `<app>.<command>`, under its shared run's key | `pswamp_models.rtsim` |

## Commands

A command reaches the source through its shared run (`live.<source>`), and the controller applies it
through `LiveTops`:

| Command | In the simulation | Reported to the graph |
|---|---|---|
| `OperateSwitchCommand(mRID, open)` | the TOPS `Switch` opened or closed | `Switch.open`, once a frame has run |
| `OperateLineCommand(mRID, in_service)` (a line with no breaker) | the line disconnected or connected | `ACDCTerminal.connected`: its first terminal out, all of them back |
| `TripBranchCommand`, `ReconnectBranchCommand` (a line or a transformer) | the branch disconnected or connected | never: a disturbance |
| `ShortCircuitCommand(mRID, y)`, `ClearShortCircuitCommand` (a connectivity node) | a fault at the node's bus, through `y` | never |
| `LoadStepCommand(mRID, p_mw, q_mvar)` | the load's power set | never |
| `FaultAndClearCommand(mRID, end, clear_ms, y)` (a line) | a fault at the bus of that end now; after `clear_ms` the breakers that isolate the line open (the line itself where it has none) and the fault goes, on time to the frame | the breakers, or the terminal, as protection's; never the fault |
| `ResetSimulationCommand` | the model built again from the graph: every disturbance gone | nothing changes in the graph |

A command for an object the running model does not have, or a switch already in that state, is
refused; so is any command while the simulation does not run.

## Protection

The controller runs it on the engine's state each time it looks at the graph (`protection.py`):

- **Overload**: a line end carrying more than `OVERLOAD_PICKUP` times its permanent current limit
  (the graph's `CurrentLimit`: the one with the longest acceptable duration, or none) trips the line
  after an inverse time, the IEC standard inverse curve `t = TMS · 0.14 / ((I/Ip)^0.02 − 1)` (with
  `OVERLOAD_TMS` 0.5: about 13 s at 1.3 times, 5 s at twice). The time is spent while the overload
  lasts and starts over when it falls back under. The sample grid has no limits; Nordic44 has 474.
- **Tripping** is by the breakers that isolate the line at both ends (`LiveTops.breakers_isolating`:
  an end shared with other equipment has none), or by the line's terminal where there are none.
  Each breaker opened is a `SimEvent` and, once applied, `CimEdits` with cause `protection`.

## What it measures

The graph's measurements (`pswamp_core.cim.measurement_table`, ADR-017): those of the grid's own
Operation profile (`Analog`s and `Discrete`s whose values come from the `PMU` or the `SCADA`
`MeasurementValueSource`), or, for a grid that has none, those the core gives it when it loads it.

**PMU, in every frame.** Each voltage level of each substation is a station, named `<substation>_<kV>`
(`Beta_400`). Each column is one PMU Analog of the graph, and carries it:

- the voltage's magnitude and angle: channel `V`, `V_Magnitude` kV and `V_Angle` deg;
- the frequency and its rate of change: channel `f`, `f` Hz (from a PLL on its bus) and `df` Hz/s (over
  the frame's steps);
- the current at a line's or a transformer's end, at the station of that end: channel `I_<branch>`,
  `I_Magnitude` A and `I_Angle` deg, from TOPS's `I_from`/`I_to` (the end is the one whose bus the
  terminal is at);
- only where the grid's PMUs measure it, the power of a generator or a load: channel `S_<equipment>`,
  `P` MW and `Q` Mvar, signed as CGMES has it (into the equipment, so a generator's is negative). The
  sample grid's and Nordic44's PMUs measure none.

A de-energised bus reads 0 kV and no angle or frequency; what the model does not have reads `None`.

**SCADA, every `SCADA_PERIOD` seconds of the simulation's clock** (`scada.py`), at the first frame and
then on: computed in the engine's process from TOPS (`SimEngine.flows`), sent up beside the frames, and
published as one `ScadaScan` of every SCADA measurement of the graph, in the units and with the sign it
declares:

- `P` MW and `Q` Mvar at a terminal of a line, a transformer, a machine or a load: the flow into the
  equipment there (`positiveFlowIn`; a measurement that says `false` reads the other way round);
- `V` kV: the line-to-line voltage's magnitude at the node; `I` A: a branch end's current;
- `Pos` (a `Discrete`, `SwitchPosition`): 1 closed, 0 open, as the simulation has the switch.

A measurement of a part the model left out has no value and is not in the scan; one of a part that
is de-energised reads what TOPS gives. The scan says the grid's model id (`cimReferenceId`) and its
time on the simulation's clock. The web backend's CIM graph app writes each scan's values as the
latest, in a graph of their own that does not move the version stamp (ADR-017).

## How it follows the graph

The simulation is LazyCIM's **`LiveTops`** (TOPS 0.6), in a **controller** (`follow.py`), which steers
the TOPS system the **engine** steps in a process of its own (`process.py`, `engine.py`).

- `LiveTops` exports the graph as a TOPS model once (`engine.EXPORT`), and builds a shadow of the
  system it never steps.
- Every `POLL` seconds (0.2) the controller looks at the graph's version stamp
  (`pswamp_core.cim.GraphVersion`: one tiny query; the writer bumps it in the same update as each
  edit). Only when it moved does it expire the profiles that change (SSH, SV) and have `LiveTops`
  follow (`exporter.refresh()`). Idle, it reads nothing but the stamp.
- `LiveTops` decides what the change means for the running simulation, and applies it to its shadow
  through a stand-in for TOPS's simulator (`runner.RemoteRunner`), which sends each event and each
  input set down the link to the engine. The engine applies it before the next frame's steps, and
  sends its state back up after each frame: what `LiveTops` reads the simulation from.
- Over a shared store (Oxigraph, `PSWAMP_CIM_URL`) the controller is **a process of its own**
  (`follow.ControllerProcess`), linked straight to the engine's: a refresh is a second or so of
  Python (results parsed into tables), which in the server's process held up the frames on their
  way to the pages, about 2.5 s without a frame at each edit. Over an in-process store (tests,
  scripts), which no other process can read, it is a thread of the source's process, at two paces:
  what the engine sends and what the simulation reports, every `POLL`; the graph, at most a quarter
  of the time, since a refresh shares the process with everything else. A report so never waits for
  the graph's back-off (it did: 14 s after a reset).

| In the graph | In the simulation |
|---|---|
| a switch opened or closed | its TOPS `Switch` opened or closed: every node is a bus and every switch a `Switch`, so the buses never change and the transient is kept; couplers included |
| a load's `p` or `q` | its power set (TOPS `set_power`), live |
| a line's or a transformer's terminal disconnected or connected again | the branch disconnected or connected (TOPS event), live, also when it cuts a part of the grid off or joins it again: that part runs on as an island, at its own frequency |
| a machine's voltage or power set-point | its exciter's or governor's bias moved (or its mechanical power, with no governor), live |
| a part left out when the model was built (below) joined to the grid again; equipment added | the model is built again and the simulation starts over at steady state, the clock running on (logged; a model that cannot be built leaves the simulation as it was) |
| anything else | logged as not followed live |

## The model

LazyCIM's TOPS export: every connectivity node a bus and every switch a TOPS `Switch` (open ones
exported open), what the slack bus cannot reach kept (LazyCIM 0.3.1, `LiveTops`'s default), a PLL on
every bus, the machines' dynamics (the graph's, else `DEFAULT_DYNAMICS`) and their governors,
exciters and stabilisers where the graph has them. Nordic44's dynamics have none, so its frequency is
not regulated.

**Islands.** A part cut off from the slack bus while the simulation runs stays in it: TOPS goes on
with it as an island (its machines keep it at their own frequency; a part with none falls to 0 V), and
every command on it applies. The engine builds what `LiveTops.built` says and applies its events
right after the initialisation. TOPS's load flow cannot initialise a part the slack bus does not
reach, so a model built (at the start, a reset, a rebuild) with a part already cut off

- builds it and cuts it off again at once, when nothing in it draws or makes power (an open bay);
- leaves it out, otherwise (`LiveTops.left_out`): it has no PMU or SCADA value, and a command on it
  is refused, saying so. It comes back, with a build, when the graph joins it to the grid again, as a
  reset of the grid does.

A bus with no admittance left (a bay whose breakers are all open, a dead island) reads 0 V: TOPS
pins it there, and the engine logs it once per bus.

**The stand-in relies on private details of `LiveTops`** (listed in `runner.py`): how a simulator
is installed, how a rebuild goes while one "runs", and that a machine's set-point is set with
`set_input` rather than an event. It goes when LazyCIM's `LiveTops` takes a runner of its own.

**Settings** (`{SOURCE}_{SETTING}`, `RTSIM_RATE` for a source named `rtsim`):
- `RATE`: frames per second (50);
- `DT`: the integration step in simulated seconds (0.01); `RATE * DT` must make whole steps per frame;
- `POLL`: the time between two looks at the graph's version stamp (0.2);
- `PROTECTION`: `on` (the default) or `off`, whether an overloaded line is tripped;
- `OVERLOAD_PICKUP` (1.0) and `OVERLOAD_TMS` (0.5): the overload relay's pickup, as a multiple of a
  line's permanent limit, and its curve's time multiplier;
- `SCADA_PERIOD`: seconds of simulated time between two SCADA scans (2); 0 scans nothing;
- `CATCH_UP`: how many times real time a simulation behind its schedule runs to catch up (1.5; 1:
  never faster than real time).

**The simulation runs in real time in a process of its own** (`process.py`, `EngineProcess`): it is
built from the model `LiveTops` exported, stepped and paced there, and each frame's values are sent
up ready; its state goes to the controller after each frame, the latest only when the controller is
busy. A TOPS step is many small
numpy calls, each taking Python's interpreter lock back when it returns; in the server every other
thread wants that lock too, so each call waits its turn (on Nordic44, four steps took 4.4 ms alone and
834 ms next to one busy thread). The pacing and the frame's values need the lock as often. So in the
server the source only turns each frame's values into a `PmuFrame`.

- **The schedule is the engine's, and nothing is dropped**: one frame period of steps per frame period
  of a monotonic clock, each frame stamped with its place in the schedule, which is never reset. So two
  frames are always one period apart, as the simulation's steps are, and a frame is the simulation's
  state at its stamp. A frame that comes late (a busy machine, a model built again) goes as soon as it
  can, but at most `CATCH_UP` times real time, so that catching up does not starve the processes the
  engine shares the machine with. A lag past a second is a warning, said again every 10 s while it
  lasts, and its end is logged; a simulation that cannot keep up falls further behind. (It used to
  drop the time past 0.25 s and stamp by the clock: two frames 0.25 s apart with 20 ms of simulation
  between them, drawn as a flat line.) The grid page shows the lag (`cim_live`'s `lag_s`).
- **It sends in batches**: a thread of the engine's process sends whatever waited as one message, so
  a server that is busy for a moment gets the frames it missed in one wake-up, and the engine never
  waits on the pipe. A frame is late then, never lost.
- The rate is logged every 10 s, as a warning below 90 % of `RATE`.

Where the graph is comes from `pswamp_core.cim` (`PSWAMP_CIM_URL`, `PSWAMP_CIM_PATH`).

A grid that cannot be read or simulated, or a run that diverges, ends the stream with the error, which
the run reports. Reading the source again starts over at t = 0 from the graph as it is then.

## Measured

Measured before the simulation moved to `LiveTops` (2026-10); the costs of the export and the
refresh are LazyCIM's, and the engine's process is unchanged. On the sample grid, in the process's own store:
- the export is about 50 queries;
- an idle refresh is 0 queries;
- a refresh after SSH expired is 4 queries (about 60 ms of rdflib).

On Nordic44 in memory:
- the export is 79 queries;
- a refresh with SSH expired is about 40 queries (1–1.7 s of rdflib);
- a step is about 1.2 ms (2.4 ms per 20 ms frame), and a frame has 407 columns;
- at 50 frames/s over 20 s: **50.0 frames/s** alone, and **51.0 frames/s next to an always-busy
  Python thread** (the backlog of the start made up), every stamp 20 ms after the last.

Before the pacing moved into the engine's process, the same run gave 9.4 frames/s next to the busy
thread; with every frame received on its own, 28.5.

Against Oxigraph, run `core/tests/test_cim_oxigraph.py` (opt-in, `PSWAMP_TEST_CIM_URL`).

## Layout

| File | What it holds |
|---|---|
| `source.py` | the stream, and what follows the graph |
| `follow.py` | `Controller`: `LiveTops` over the graph; `ControllerProcess`, the same in a process of its own |
| `runner.py` | `RemoteRunner`: the stand-in through which `LiveTops` steers the engine |
| `protection.py` | the overload relay's curve, and what has spent its time |
| `engine.py` | `SimEngine`, the TOPS system the engine steps, and what it is sent |
| `process.py` | `EngineProcess`: the engine, paced in real time, in a process of its own |
| `pmu.py` | the PMU layout, from the graph's Analogs |

## From a script

    uv run --package pswamp-rtsim-from-cim --extra examples python modules/rtsim-from-cim/examples/run_rtsim.py [--save f.png]

It opens a breaker by editing its own in-process graph (`pswamp_core.cim.testing.edit`). A
deployment never does that: there, the web backend is the only writer.

**Over a store of the script's own.** `RtsimFromCimSource(repo=repo)` reads any LazyCIM
repository instead of the one the settings name: a demo model in an embedded Oxigraph, a GraphDB
repository. The source then owns that repository and follows it from a thread (a repository
cannot cross into another process); the script edits the grid through a second repository over
the same store. Such a store has no version stamp, so the source re-reads what changes every
couple of seconds (`pswamp_core.cim.GraphVersion`). Ready the grid first with
`pswamp_core.cim.prepare(repo)`, and read through a repository made after it, which sees the
graphs `prepare` created. `CimSettings(backend=..., shared=True)` names a store that another
process can open too, and is followed from a process of its own, as Oxigraph is.
`modules/frame-stats/examples/rtsim_frame_stats.py` is the worked example, and names this source
by its entry point rather than importing it.

## Tests

`uv run pswamp test module rtsim-from-cim` (also part of `uv run pswamp test server`), over the
sample grid. The Nordic44 test is skipped unless LazyCIM has it cached, and the edits unless it has
the CGMES vocabularies.

## Dependency

`pswamp-core[cim]` and LazyCIM (`LiveTops`, `0.3.0`), TOPS 0.6
for the simulation, numpy and scipy.
