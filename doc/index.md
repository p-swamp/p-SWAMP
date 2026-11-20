# p-SWAMP

**Power Stability Wide Area Monitoring and Protection.**

p-SWAMP watches a power grid through fast, time-synchronised measurements and
helps spot trouble as it happens: a line that trips, a part of the grid that
splits off and runs on its own, a frequency that drifts away from 50 Hz. It is a
platform for developing and testing such monitoring applications, on recorded,
simulated or live data, before they go anywhere near a control room.

---

## Start here

<div class="grid cards" markdown>

-   :material-rocket-launch: **[Getting started](start/what-you-need.md)**

    Install two tools, start p-SWAMP, and watch a recorded grid disturbance
    in your browser.

-   :material-lightbulb-on: **[Concepts](concepts/wampac.md)**

    What wide area monitoring is, what a PMU measures, and how p-SWAMP turns
    those measurements into something you can see.

-   :material-puzzle: **[Modules](modules/index.md)**

    The building blocks: where the data comes from, and the analyses that run
    on it.

-   :material-account-group: **[Contributing](project/contributing.md)**

    Set up a development copy, add a module of your own, and send it back.

</div>

## What you can do with it

**Replay a disturbance and watch it unfold.** p-SWAMP ships with a recording of
the Nordic 44 test grid during a line trip and its reconnection. The monitor
replays it in real time: the grid on a map, the frequency of every station, the
voltage phasors, and the alarms raised when part of the grid is cut off.

**Operate a simulated grid.** A real-time simulation of the grid runs behind a
map. Open a breaker, trip a line or cause a short circuit, and see the
frequency and voltages respond, measured as PMUs would measure them.

**Test an analysis before it is trusted.** An analysis is a module: a small
piece of Python with a clear input and output. The same module runs in a plain
script on your laptop, in the web application, or as a separate process beside
it, with no change to its code.

## Who it is for

- **Power system engineers and researchers** who want to try a monitoring or
  protection idea on realistic data, and see the result.
- **Developers** building those applications, who want a tested platform to
  build them on rather than a blank page.
- **Grid operators** evaluating what wide area monitoring could show them.

## Where it comes from

p-SWAMP grew out of the research project
[NEWEPS](https://ri.diva-portal.org/smash/record.jsf?pid=diva2%3A1933825&dswid=2773).
It is an open source project hosted by [LF Energy](https://lfenergy.org/), under
the Apache-2.0 licence. See [About](project/about.md) for who is behind it.

!!! warning "Research code"

    p-SWAMP is developed as part of ongoing research and contains experimental
    features. Use it at your own risk, and validate its results before relying
    on them.
