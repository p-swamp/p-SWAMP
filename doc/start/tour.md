# A tour

With p-SWAMP [running](first-run.md), the bar at the top of the page leads to
each part of it. This page shows what each one is, and what to try.

There is one simulated grid, shared by everyone connected to the same server:
what one person does to it on the **CIM graph** page, everyone sees on the
monitor, and an alarm one person acknowledges is acknowledged for all. Nothing
is saved: a restart puts the grid back as it was loaded. The PMU test streamer
is the exception: there each browser gets a replay of its own.

## The monitor

<figure markdown>
![The monitor: the sample grid's three substations drawn in 3D over a map of the Nordic countries, marked "Intact"; on the right, the list of monitoring applications, a flat frequency chart at 50 Hz, a status table with both monitoring modules OK and the simulation streaming, and one cleared islanding alarm.](../assets/screenshots/monitor.png)
<figcaption markdown>The monitor over p-SWAMP's small sample grid, three
substations in southern Norway, with the grid whole. The alarm listed was raised
when both lines into one substation were opened, and cleared once the grid was
put back.</figcaption>
</figure>

The **Monitor** is the main window. It shows the simulation of the grid running
behind the CIM graph page, measured by a PMU at every station 50 times a second,
and what p-SWAMP's monitoring modules make of it, as it happens.

- **The grid view** in the middle draws the grid over a map of the Nordic
  countries. Each separate part of the grid (an *island*) has its own colour, and
  is raised or lowered by how far its frequency is from 50 Hz. Drag to turn it,
  or switch to **2D**. **Layers** spreads the frequency or the voltage over the
  map as a colour field.
- **Frequency** plots every station's frequency over the last few seconds.
- **Status** shows each monitoring module and what it currently reports, and
  whether the simulation is streaming.
- **Alarms** lists what the modules raised. Click one to see its details,
  acknowledge it, and add a note.
- **Voltage phasors** draws each station's voltage as an arrow: its length is
  the voltage, its angle the phase. When the grid is stressed, the arrows fan
  out.
- **Line outages** lists the lines whose current dropped to zero, and when they
  came back.

**What to try.** Nothing happens to the grid on its own. On the CIM graph page,
open every line into one substation: on the monitor, that part of the grid
becomes an island with a colour of its own, the islanding detector raises an
alarm, and the line outage detector lists the lines that went out. Close them
again, or press **Reset grid**, and the island rejoins.

Each panel has an expand button (:material-arrow-expand:) that opens it on a
page of its own, full size.

## The CIM graph

<figure markdown>
![The CIM graph page: three substations joined by lines on an OpenStreetMap map of southern Norway, with generator and load symbols; below, a frequency chart falling from 50 Hz to about 48 Hz and recovering, and voltages sagging.](../assets/screenshots/cim-graph.jpg)
<figcaption markdown>The CIM graph page showing p-SWAMP's small sample grid,
a few seconds after a load was stepped up: the frequency falls and the voltages
sag. Map data © OpenStreetMap contributors.</figcaption>
</figure>

The **CIM graph** page runs a simulation of a grid in real time, and lets you
operate it. The grid comes from a model in the standard format grid operators
exchange (CIM/CGMES); by default it is the Nordic 44 test grid.

- **Click a breaker** (the small squares) to open or close it.
- **Click a line, a substation, a generator or a load** to see what the model
  says about it, its live values and their last 30 seconds.
- **Right-click** one of them (a long press on a touch screen) to disturb the
  simulation: trip a line, cause a short circuit, or change a load. Protection
  clears a fault the way real protection relays would.
- **The charts** below the map show every station's frequency and voltage over
  the last 30 seconds.
- **Reset grid** puts everything back.

Lines are coloured by how heavily they are loaded. A disturbance never changes
the model itself, only the simulation; what the simulated protection does in
response (open breakers) does change it, as it would in a real control system.

## The PMU test streamer

<figure markdown>
![The PMU test streamer: a table of five stations with voltage, angle and frequency; a choice of source (sample, live); the frame statistics, excursion and summary results; and player controls with a timeline.](../assets/screenshots/pmu-test-streamer.png)
<figcaption>The PMU test streamer, paused at the start of the sample recording.</figcaption>
</figure>

The **PMU Test Streamer** is a workbench for p-SWAMP's building blocks rather
than a monitoring screen. It shows one stream of measurements going through a
chain of [modules](../modules/index.md):

- **The source**: choose between the short sample recording (*sample*), a looping
  imitation of a live feed (*live*), and an installation's measurement archive
  (*remote*), where one is configured.
- **The player**: play, pause, step, jump to an instant or change the speed of a
  recording. A live source can only be followed.
- **The results** of three analysis modules: [frame statistics](../modules/frame-stats/index.md)
  (average frequency, angle spread), [excursions](../modules/excursion/index.md)
  of the frequency outside a band around 50 Hz (tick *pause on excursion* to stop
  the replay when one happens), and a [summary](../modules/range-summary/index.md)
  of the next second, on request.

Developers use it to check that a change to p-SWAMP's core still works end to
end.

## Islanding detection

The **Islanding detection** page shows the latest result of the
[islanding detection](../modules/islanding-detection/index.md) module on its
own: whether the grid is whole, and its alarm while one is active. It is the
same module the monitor uses, on a page that shows nothing else.

## The reference example

The **Reference example** is a counter, and deliberately nothing more. It is the
smallest complete page of the web application, the one to copy when building a
new one, and the one the automated tests click through to prove the whole
application still works.

## Next

- [Concepts](../concepts/wampac.md): what the measurements are, and how p-SWAMP
  handles them.
- [From a script](from-a-script.md): run the same analyses without the web
  application.
