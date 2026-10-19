# rtsim-from-cim

`pswamp-rtsim-from-cim`, package `pswamp_modules.rtsim_from_cim`, class
`RtsimFromCimSource`, entry point `rtsim-from-cim` (group `pswamp.modules`).

A **live source**: a TOPS dynamic simulation of the grid in the **CIM graph**, run in real time.
The graph is the one copy of the grid (`pswamp_core.cim`, ADR-014), and it is how the simulation is
steered: whoever edits the graph (the web backend's CIM graph app, its only writer) steers it. There
are no commands. Not playable: a run follows the source as it goes.

| | Message | Topic | Defined in |
|---|---|---|---|
| Reads | nothing on the transport (the CIM graph, through its own repository: `cim = True`) | | |
| Emits | `PmuFrame` (mRID `rtsim-from-cim`): one column group per PMU Analog of the graph, each column carrying its Analog (`header.analog`) | `pmu.frame` | `pswamp_models.pmu` |
| Accepts | nothing | | |

## What it measures

The graph's PMU Analogs (`pswamp_core.cim.analogs`). Each voltage level of each substation is a
station, named `<substation>_<kV>` (`Beta_400`). It has:

- a voltage phasor: `V_Magnitude` kV, `V_Angle` deg;
- a frequency: `f` Hz, from a PLL on its bus;
- the current of each line leaving it: channel `I_<line>`, `I_Magnitude` A, `I_Angle` deg, from TOPS's
  `I_from`/`I_to`.

A de-energised bus reads 0 kV and no angle or frequency.

## How it follows the graph

- `follow.py`: LazyCIM exports the graph as a TOPS model once
  (`get_exporter("tops", repo, **engine.EXPORT).build()`).
- Every `POLL` seconds (0.2) it looks at the graph's version stamp (`pswamp_core.cim.GraphVersion`:
  one tiny query; the writer bumps it in the same update as each edit). Only when it moved does it
  expire the profiles that change (SSH, SV) and bring the export up to date with `exporter.refresh()`.
  Idle, it reads nothing but the stamp.
- Over a shared store (Oxigraph, `PSWAMP_CIM_URL`) it runs in **a process of its own**
  (`follow.FollowerProcess`) and sends what changed straight down a pipe to the engine's process,
  which applies it before the next frame's steps (`engine.py`). A refresh is a second or so of
  Python (results parsed into tables); in the server's process it held up the frames on their way
  to the pages, about 2.5 s without a frame at each edit. Over an in-process store (tests,
  scripts), which no other process can read, it is a thread of the source's process.
- Measured on the sample grid: 0.25 s from the edit to the frames. On Nordic44, applying a line
  flip in the engine takes 1 ms (a `Line.event`, not a rebuild); the refresh is the cost.

| In the graph | In the simulation |
|---|---|
| a switch opened or closed | `Line.event` on the switch's own branch: every switch is a branch (`switches_as_branches`), so the buses never change and the transient is kept; couplers included |
| a load's `p` or `q` | its admittance moves, live |
| a line's terminal disconnected or connected again (its row goes or comes back) | `Line.event` on the line, like a switch |
| a transformer's terminal disconnected or connected again (its row goes or comes back) | its admittance comes off the network, or goes back on (`SimEngine._transformer`: TOPS has no transformer event), and its currents read 0 while it is out |
| other rows come or go (equipment added) | the model is built again, without the buses the slack cannot reach, and the simulation starts over at steady state (logged; a model that cannot be built leaves the simulation as it was) |
| anything else | logged as not followed live |

## The model

LazyCIM's TOPS export: open switches exported closed and tripped after the load flow, a PLL on every
bus, the machines' dynamics (the graph's, else `DEFAULT_DYNAMICS`) and their governors, exciters and
stabilisers where the graph has them. Nordic44's dynamics have none, so its frequency is not
regulated.

Every bus gets a 0.001 Mvar shunt to ground. On Nordic44 the open switches leave bay nodes floating,
which made the network singular.

A transformer whose two windings are in two substations is drawn on the grid page as a branch
between them, like a line (Nordic44's `MO T1`, Mo-Narvik), and taken out the same way: by a
terminal, since it has no bay. Before transformers were followed live, that made the simulation
start over at steady state, a few seconds without a frame.

The export of LazyCIM 0.2.1 listed each breaker twice, as a Switch and as a Breaker (0.2.2 does
not); the engine keeps one row per name.

**Settings** (`{SOURCE}_{SETTING}`, `RTSIM_RATE` for a source named `rtsim`):
- `RATE`: frames per second (50);
- `DT`: the integration step in simulated seconds (0.01); `RATE * DT` must make whole steps per frame;
- `POLL`: the time between two looks at the graph's version stamp (0.2).

**The simulation runs in real time in a process of its own** (`process.py`, `EngineProcess`): it is
built, stepped and paced there, and each frame's values are sent up ready. A TOPS step is many small
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

On the sample grid, in the process's own store:
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
| `follow.py` | the export and its refresh; `FollowerProcess`, the same in a process of its own |
| `engine.py` | `SimEngine`, the pure stepper, and how a change is applied |
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

`pswamp-core[cim]` (LazyCIM `0.2.2`), TOPS for the simulation, numpy and scipy.
