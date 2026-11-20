# Modules

p-SWAMP is built from small, independent pieces called **modules**. Each one does
one job, and a pipeline connects them: measurements come in at one end, and
results, alarms and charts come out at the other.

There are two kinds:

- A **source** brings measurements in. It reads nothing from the other modules;
  it produces a stream of PMU frames (one snapshot of every measuring station, many
  times a second), from a recording, a simulation or a live feed.
- An **analysis module** reads what a source or another module produces, computes
  something from it, and publishes the result for the next module or for the screen.

Each module has its own section below: an overview of what it does and how to use
it, and an API reference generated from its code.

## Sources

| Module | What it is for |
|---|---|
| [sample-replay](sample-replay/index.md) | Replays a short recording that ships with p-SWAMP: three seconds of five stations in the Nordic 44 test grid, during a line trip. The quickest way to see anything work. |
| [live-synthetic](live-synthetic/index.md) | Pretends to be a live measurement feed, by looping that same recording with the current time on every frame. For testing what reacts to live data. |
| [synthetic-history](synthetic-history/index.md) | Pretends to be a year-long measurement archive, with gaps, computed on the fly so it takes no disk space. For testing what browses history. |
| [remote-history](remote-history/index.md) | Reads the measurement archive of a real installation, through a small web service that installation provides. How p-SWAMP reaches real historical data without storing any itself. |
| [rtsim-from-cim](rtsim-from-cim/index.md) | Simulates the grid in real time and measures it as PMUs would. You can open breakers, trip lines and cause faults, and watch the grid respond. |

## Analysis modules

| Module | What it is for |
|---|---|
| [frame-stats](frame-stats/index.md) | For every snapshot, the average, lowest and highest frequency across the stations, how far apart their voltage angles are, and the average voltage. |
| [excursion](excursion/index.md) | Watches the average frequency from frame-stats and counts each time it leaves a band around 50 Hz. It can pause a replay at the moment it happens. |
| [range-summary](range-summary/index.md) | Answers a question about a period of time: how many snapshots it holds, and the lowest, highest and average frequency over it. |

## Writing a module

A new module starts from the generator and follows the
[module cookbook](../module-cookbook.md). Its README becomes its overview page
here, a `docs/` folder beside it adds pages of its own, and its docstrings
become its API reference, with nothing to configure.
