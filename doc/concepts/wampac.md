# Wide area monitoring

This page explains, without assuming a background in power systems, what
p-SWAMP watches and why.

## A grid has one heartbeat: its frequency

Every generator connected to a power grid spins in step with all the others.
In the Nordic grid that common speed corresponds to a frequency of **50 Hz**.
The frequency is the grid's heartbeat, and it is the same everywhere in a
connected grid.

It moves when the balance between production and consumption moves. When a
large power plant stops, or a large load starts, the frequency falls; when
consumption drops, it rises. Control systems then bring it back. A frequency
that strays far from 50 Hz is a sign of trouble, and beyond certain limits
equipment disconnects itself to stay safe, which can make things worse.

## When a grid splits: islands

A grid is a web of lines. If enough lines trip at once, part of the grid can be
cut off from the rest, and runs on its own: an **island**. An island has its own
frequency, which no longer follows the main grid's. Spotting an island quickly
matters: it must be handled before it is reconnected, or the two parts may be
out of step when they meet.

## Measuring the grid: PMUs

A **phasor measurement unit** (PMU) is an instrument at a substation that
measures the voltages and currents there, together with their *phase*: where
each one is in its 50 Hz cycle at that instant. Every PMU stamps its
measurements with the time from GPS, so measurements taken hundreds of
kilometres apart can be compared at the same instant. A PMU reports many times
a second (50 times, in p-SWAMP's grid simulation).

A voltage measured this way is a **phasor**: a size (the voltage) and an angle
(its phase). Comparing the angles of two stations shows how hard the grid is
working to move power between them; a sudden change in the angles means
something happened.

Traditional measurements (**SCADA**) report every few seconds and are not
synchronised. They are good for a steady picture of the grid, too slow to see a
disturbance unfold. PMUs see it as it happens.

## Wide area monitoring, protection and control

Put PMUs across a whole grid, bring their measurements to one place, and you
can watch the grid as a whole, in real time: **wide area monitoring**. Applications
that run on those measurements can then warn an operator (monitoring), act to
protect equipment (protection), or steer the grid back to safety (control).
Together they are called **WAMPAC**: wide area monitoring, protection and control.

p-SWAMP is a platform for building and testing such applications. In it:

- the **islanding detection** application spots parts of the grid that have
  separated, from stations whose measurements stop moving together;
- the **line outage detection** application spots lines that have stopped
  carrying current;
- further analyses are added as [modules](../modules/index.md).

## Test grids

p-SWAMP is tested on **Nordic 44**, a model of the Nordic grid simplified to 44
stations, built for research. It behaves like the real grid without being it,
so recordings and simulations of it can be shared freely for research (see
[data licensing](../project/data-licensing.md)).

## Next

[How p-SWAMP works](how-it-works.md): how measurements travel from a source,
through analyses, to your screen.
