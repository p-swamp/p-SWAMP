# ADR-019: Keep alarm records in the recorder, and read an alarm's measurements from wherever they are kept

- Status: Proposed
- Date: 2026-11-27

## Context

An operator must be able to open an alarm from a week ago, or older, and see what happened:
the measurements around it, the module's assessment, and what operators did with it. Today
none of that outlives the server process. The alarm list (`pswamp_web.stores.AlarmStore`)
and each alarm's capture (`grid_monitor/capture.py`: every station's f, |V| and ∠V at full
rate, plus each islanding assessment) are kept in memory. A restart loses them, and only the
newest 20 captures are kept, at most 15 min each. Memory sets the limit as well: 20 captures
of 10 min on Nordic44 take about 350 MB.

There are two deployments, and they differ in where the measurements live:

- **Simulation.** The frames come from `rtsim` and exist nowhere else. If p-SWAMP does not
  keep them, nobody does.
- **A live PMU feed with an archive behind it.** The deployment already stores months of
  frames and serves them through the remote data contract (ADR-012). A copy in p-SWAMP would
  duplicate that archive.

In both, alarms, operator actions and module results are p-SWAMP's own, so only p-SWAMP can
keep them. The recorder (ADR-018) now stores any recordable message, not only frames
(`MESSAGES`). Module results are recordable already; `AlarmEvent` and `AlarmAction` are not.

Module results are also expensive to recompute and read by many. A heavy module computes an
alarm's assessment once, and several operators open the alarm within minutes of it being
raised, when it matters most that the view opens at once. Weeks later the same alarm is
opened rarely, and waiting a few seconds for it is acceptable.

Running a module over older data, for example to find the events of last March, is wanted
later. It need not be a shared run, nor be started from the GUI. Its alarms should still be
viewable in the GUI.

## Decision

**We will keep p-SWAMP's own records in the recorder, in every deployment.** These are the
alarms (`AlarmEvent`), operator actions (`AlarmAction`) and module results. Both alarm
models become `recordable = True`. The grid monitor's pipeline gets a recorder, fed by its
live run, whose `MESSAGES` name these topics.

**We will read an alarm's measurements from a history source that is named in configuration,
never from a copy of our own.** The recorder and `remote-history` are both history sources
(`read(start, end)`, `coverage()`), so the alarm view does not need to know which one it is
reading. The pipeline file names which source holds the records and which holds the frames:

- simulation: the same recorder, with `PmuFrame` in its `MESSAGES`;
- live feed with an archive: a `remote-history` source, and the recorder does not keep frames.

When no source of frames is configured, the alarm view shows live data only and says that no
capture is available.

**We will serve an alarm's results in two tiers.**

- **Recent:** the results the module published are read back from the recorder. Nothing is
  computed when the alarm is opened.
- **Older:** once the stored results have expired, the server reads the frames from the
  history source and runs the module over them with its ordinary synchronous call. The read
  starts the module's window ahead of the alarm, so the window is full by the alarm's start.
  The computation runs off the event loop, and its result is stored, so the next viewer reads
  it.

What the operator acted on is never recomputed. The alarm, and the assessment in force when
it was raised, are kept for as long as the alarm. Only the stream of results around the alarm
expires. Each stored result records its module's version and parameters, so a recomputation
made under a different module can be told apart.

**We will keep the alarm list in memory, and fill it from the recorder at start.** The
panels read `AlarmStore` on every wake-up, and it stays the only state they read. At start,
the server replays the recorded alarms and actions since a cutoff into a fresh store, so
active alarms and their acknowledgements survive a restart. Older alarms are listed by a
history endpoint over the recorder, not held in the store.

**We will retire the in-memory capture store** (`AlarmCaptures`) once the capture endpoints
read through a history source. The alarm view keeps extending its chart from the live stream
(`useAlarmCapture.ts`), so the recorder's flush delay is not visible.

**We will let a script's alarms join the live alarm list.** Running a module over older data
is a script, as every module already supports: a history source's `read(start, end)` into
the module's `run()`. The script sends each alarm it raises to the server with a POST command.
The server publishes it on the live run, as it does an operator's `AlarmAction`. Every alarm
says where it came from (`origin`: the live run, or an offline run with its id and who
started it). An imported alarm has a key (module, parameters, start time), so running the
same period twice adds nothing.

**We will run the recorder in the grid monitor always, and make a persistent volume
optional.** Its `DIR` may be a temporary directory (`emptyDir` in k8s, a container path in
compose and CI). With one, the stack behaves as today: everything is gone after a restart, on
disk instead of in memory. With a volume mounted, history is kept. This amends ADR-018, under
which the recorder runs only when a deployment opts in.

## Consequences

- An alarm from weeks or months ago can be opened, in both deployments, within the
  recorder's retention for its records and the archive's for its frames.
- The grid monitor's memory no longer grows with alarms: up to about 350 MB on Nordic44 moves
  to disk or to the archive.
- The stack writes files in every deployment, temporary unless a volume is mounted. The
  rule "nothing depends on the volume being present" still holds. "The stack persists
  nothing" becomes "the stack persists nothing unless a volume is mounted".
- The recorder needs a retention limit by age, separately per topic (for example results 30
  days, alarms and actions longer). Today it has only a size limit (`MAX_BYTES`).
- The recorder must be tested recording without `PmuFrame`.
- **The remote data contract needs column selection and min/max decimation.** A 10-minute
  Nordic44 alarm is about 30,000 frames of about 500 columns, which is hundreds of MB of
  NDJSON. That is too much to draw a 2,000-point overview, and recomputing a module over it
  reads every column at full rate. Until the contract has them, the overview is computed
  once, when the alarm clears, and stored as a small record of its own.
- A recomputed result may differ from what was shown when the alarm was raised, if the module
  changed in between. The stored alarm and its assessment at the time are the record of what
  the operator saw. The recomputation is an analysis, labelled with its module version.
- Operator names and notes become stored records with a retention period. Access to them, and
  how long they are kept, follows the rules on personal data.
- The recorder's message selection (`MESSAGES`, branch `feat/recorder`) has to be merged onto
  the live grid first; that branch predates `pipelines/grid-monitor.toml` and `AlarmAction`.
- Running a module over older data in the GUI, or as a shared run, stays out of scope. It
  would need a decision on how per-user runs relate to the shared alarm list (ADR-009).

## Alternatives considered

- **Keep captures in memory only:** an alarm is lost at restart or after 19 newer ones, and
  memory grows with the grid's size.
- **Record every frame continuously in both deployments:** about 17 GB a day uncompressed on
  Nordic44, and a duplicate of the archive in a live deployment.
- **Record frames only around alarms, as a disturbance recorder does:** right for the
  simulation when continuous recording is too large. It can be added to the recorder later
  without changing this decision, since the alarm view reads through a history source either
  way.
- **Keep both the in-memory capture and the recorder:** two implementations of the capture
  endpoints, and two copies of the same data, to test and keep equal.
- **Derive the alarm list from the recorder on every read:** too slow for the panels' wake-ups,
  one flush behind, and no list at all if the recorder fails.
- **Always recompute results, never store them:** the newest alarms, which are read by the
  most people and needed quickest, would cost the most.
- **Let the script write its alarms to the recorder directly:** a second writer, and the live
  list would not hear of them. Publishing on the run keeps one path for every change to the
  alarm list.
