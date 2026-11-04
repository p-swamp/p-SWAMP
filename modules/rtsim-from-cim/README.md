# rtsim-from-cim

`pswamp-rtsim-from-cim`, package `pswamp_modules.rtsim_from_cim`, class
`RtsimFromCimSource`, entry point `rtsim-from-cim` (group `pswamp.modules`).

A **live source**: a TOPS dynamic simulation of the grid in the **CIM graph**, run in real time.
The graph is the one copy of what is *known* of the grid (`pswamp_core.cim`, ADR-014); the
simulation is what *is* (ADR-015). It is steered by **commands**, and it also follows the graph:
whoever edits the graph (the web backend's CIM graph app, its only writer) steers it too. Not
playable: a run follows the source as it goes.

| | Message | Topic | Defined in |
|---|---|---|---|
| Reads | nothing on the transport (the CIM graph, through its own repository: `cim = True`) | | |
| Emits | `PmuFrame` (mRID `rtsim-from-cim`): one column group per PMU Analog of the graph, each column carrying its Analog (`header.analog`) | `pmu.frame` | `pswamp_models.pmu` |
| Emits | `SimEvent`: every command applied, announced at once | `sim.event` | `pswamp_models.rtsim` |
| Emits | `CimEdits` (producer `rtsim`): an operation, once the engine applied it, for the graph's one writer | `cim.edits` | `pswamp_models.cim` |
| Accepts | `OperateSwitchCommand`, `OperateLineCommand` (operations); `TripBranchCommand`, `ReconnectBranchCommand`, `ShortCircuitCommand`, `ClearShortCircuitCommand`, `LoadStepCommand` (disturbances); `ResetSimulationCommand` | `<app>.<command>`, under its shared run's key | `pswamp_models.rtsim` |

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
| `ResetSimulationCommand` | the model built again from the graph: every disturbance gone | nothing changes in the graph |

A command for an object the running model does not have, or a switch already in that state, is
refused; so is any command while the simulation does not run.

## What it measures

The graph's PMU Analogs (`pswamp_core.cim.analogs`). Each voltage level of each substation is a
station, named `<substation>_<kV>` (`Beta_400`). It has:

- a voltage phasor: `V_Magnitude` kV, `V_Angle` deg;
- a frequency: `f` Hz, from a PLL on its bus;
- the current of each line leaving it: channel `I_<line>`, `I_Magnitude` A, `I_Angle` deg, from TOPS's
  `I_from`/`I_to`.

A de-energised bus reads 0 kV and no angle or frequency.

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
  scripts), which no other process can read, it is a thread of the source's process.

| In the graph | In the simulation |
|---|---|
| a switch opened or closed | its TOPS `Switch` opened or closed: every node is a bus and every switch a `Switch`, so the buses never change and the transient is kept; couplers included |
| a load's `p` or `q` | its power set (TOPS `set_power`), live |
| a line's or a transformer's terminal disconnected or connected again | the branch disconnected or connected (TOPS event), live, when no part of the grid is cut off by it |
| a machine's voltage or power set-point | its exciter's or governor's bias moved (or its mechanical power, with no governor), live |
| a part of the grid cut off from the slack bus, or brought back; equipment added | the model is built again, without what the slack bus cannot reach, and the simulation starts over at steady state, the clock running on (logged; a model that cannot be built leaves the simulation as it was) |
| anything else | logged as not followed live |

## The model

LazyCIM's TOPS export: every connectivity node a bus and every switch a TOPS `Switch` (open ones
exported open), what the slack bus cannot reach left out, a PLL on every bus, the machines' dynamics
(the graph's, else `DEFAULT_DYNAMICS`) and their governors, exciters and stabilisers where the graph
has them. Nordic44's dynamics have none, so its frequency is not regulated.

A bay node that open switches leave floating reads 0 V: TOPS pins a bus without admittance to 0 V.

**The stand-in relies on private details of `LiveTops`** (listed in `runner.py`): how a simulator
is installed, how a rebuild goes while one "runs", and that a machine's set-point is set with
`set_input` rather than an event. It goes when LazyCIM's `LiveTops` takes a runner of its own.

**Settings** (`{SOURCE}_{SETTING}`, `RTSIM_RATE` for a source named `rtsim`):
- `RATE`: frames per second (50);
- `DT`: the integration step in simulated seconds (0.01); `RATE * DT` must make whole steps per frame;
- `POLL`: the time between two looks at the graph's version stamp (0.2).

**The simulation runs in real time in a process of its own** (`process.py`, `EngineProcess`): it is
built from the model `LiveTops` exported, stepped and paced there, and each frame's values are sent
up ready; its state goes to the controller after each frame, the latest only when the controller is
busy. A TOPS step is many small
numpy calls, each taking Python's interpreter lock back when it returns; in the server every other
thread wants that lock too, so each call waits its turn (on Nordic44, four steps took 4.4 ms alone and
834 ms next to one busy thread). The pacing and the frame's values need the lock as often. So in the
server the source only turns each frame's values into a `PmuFrame`.

- **The schedule is the engine's**: one frame period of steps per frame period of a monotonic clock,
  each frame stamped with its place in the schedule. A frame that comes late is made up by the next
  ones; more than `MAX_LAG` (0.25 s) behind, the lost time is dropped.
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
