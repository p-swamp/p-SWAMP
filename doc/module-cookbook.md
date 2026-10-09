# Module cookbook

How to add an analysis module to the server data architecture, show its
results on a page, send it commands, and run it in a process of its own.
`doc/server-data-architecture.md` explains the pieces; this is the recipe.

It goes in two parts, then recipes:

1. **The module**: the server side. Write the analysis and test it, without
   the pipeline running.
2. **The frontend**: the web API and the page that show the module's results.
3. **Further recipes**: commands, chaining, windows and kept results, batch
   queries, a worker of its own, scaling, data sources.

The examples come from three apps:
- **`peak-frequency`**: what the generator writes below. One module, one page.
- **`rolling-frequency`** (`modules/pswamp_modules/rolling_frequency/`; its
  web API in `app/server-python/src/rolling_frequency/`): one module with a
  five-second window over a 30 s recording, whose results the server keeps
  and shows again. The example for "Caching and windowed algorithms".
- **The PMU test streamer** (`frame_stats/`, `excursion/`, `range_summary/`
  and `pipelines/pmu_test_streamer.py` in `modules/pswamp_modules/`; its
  web API in `app/server-python/src/pmu_test_streamer/`): the reference
  example, with three modules. `FrameStatsModule` computes each
  frame's statistics, `ExcursionModule` watches those statistics for the
  frequency leaving its band, and `RangeSummaryModule` summarizes a time range
  of a recording on command.

## Generate the starting point

```
./scripts/generate-new-module-with-frontend.sh peak-frequency "Peak frequency"
```

This writes a working app, registers it everywhere, regenerates the api
contract and runs `error_check.sh`.

The module, in `modules/`. Part 1 is about these:

| File | What it holds |
|---|---|
| `modules/pswamp_modules/peak_frequency/module.py` | the module: what it reads, what it publishes, `process`. Its analysis is a placeholder: the station with the highest frequency |
| `modules/pswamp_modules/peak_frequency/tests/test_module.py` | the module's tests, beside its code |
| `modules/pswamp_modules/pipelines/peak_frequency.py` | the pipeline: the app's name, its sources, its modules |

A starting frontend, in `app/`:

| File | What it holds |
|---|---|
| `app/server-python/src/peak_frequency/api.py` | the web API: the run registry, the socket's state message |
| `app/server-python/tests/test_peak_frequency.py` | the web API's test |
| `app/client-web/src/pages/peak-frequency/` | the page at `/peak-frequency` and its socket hook |

The frontend files give the module a page from the start: it shows the
module's latest result, and needs no change while you work on the module.
Part 2 comes back to them.

The registrations: entries in `server.py`, the route table, the nav,
`lib/servers.ts`, and the module-worker's lists in `docker-compose.yml` and
`k8s/p-swamp-local.yaml`.

## Part 1: The module

A module is one folder, `modules/pswamp_modules/<pkg>/`, holding its code
and its tests. It and its pipeline import the core only: never the web backend
(`shared`, `fastapi`, `pswamp_web`). A worker then hosts the module without
loading the server. `pswamp_modules/tests/test_layering.py` fails if one does.

So the work in this part needs no server, no broker and no browser: write the
analysis, and run its tests.

### Write the analysis

In `modules/pswamp_modules/peak_frequency/module.py`, replace
`highest_frequency` and the result body it fills. Keep the analysis a plain
function and `process` a thin adapter: the function is then testable with plain
values.

```python
class PeakFrequencyModule(Module):
    name = "peak-frequency"                 # its identity in results, logs and the tray
    input_model = PmuFrame                  # what it reads
    output_model = PeakFrequencyResult      # a ResultEnvelope subclass: what it publishes

    warm_up_s = 0.0                         # for an analysis that needs a window: off here, and
    cache_results = False                   # described in the file, with `reset()`, where they stand

    async def process(self, frame: PmuFrame) -> PeakFrequencyBody | None:
        columns = frame.header.columns(measurement="f")     # the layout rides in every frame
        ...                                                 # return None to publish nothing
```

- The layout is in `frame.header`. A module that derives something from it
  (column indexes) re-derives it when `frame.header.header_id` changes; the
  streamer's `frame_stats/module.py` does.
- The CIM reference for the frame is `frame.header.cimReferenceId`.
- An analysis that answers from one frame leaves `warm_up_s`, `cache_results`
  and `reset` as generated. One that needs several frames before it can
  answer sets them: "Caching and windowed algorithms", below.
- A result class is a `ResultEnvelope[Body]` subclass with
  `version: Literal["v1"] = "v1"`. Its name is its topic
  (`PeakFrequencyResult` → `peak.frequency.result`), and the browser's type is
  generated from it.

### Test it without the pipeline

```
./scripts/run-python-server-tests.sh ../../modules/pswamp_modules/peak_frequency
```

This runs the module's own folder and nothing else. The path is relative to
`app/server-python/`, where the runner starts pytest.

Three levels, bottom up. The generated `tests/test_module.py` has the first
two:

1. **The analysis**: call the function with plain values.

   ```python
   assert highest_frequency(["a", "b", "c"], [49.9, 50.1, 50.0]) == ("b", 50.1)
   ```

2. **The module**: build a `PmuFrame` by hand (the `frame()` helper in the
   generated tests) and await `process` directly.

   ```python
   body = await PeakFrequencyModule().process(frame([49.9, 50.1, None]))
   assert (body.station, body.frequency_hz) == ("s1", 50.1)
   ```

   A module with state, or one that publishes on its own, is driven the same
   way: `await module.setup(out)` with an `out` that records what is
   published, then `process` and `handle` in the order under test.
   `excursion/tests/test_module.py` does.

3. **The module, hosted**: a `ModuleHost` over an `InMemoryTransport`. Publish
   a frame on the input topic and read the result off the output topic. There
   is still no server, source or player. It checks what the first two cannot:
   the topics, the run key, and the result envelope.

   ```python
   import asyncio

   from pswamp_core.host import ModuleHost
   from pswamp_core.transport import InMemoryTransport
   from pswamp_core.util.tasks import cancel_and_wait
   from pswamp_modules.peak_frequency import PeakFrequencyModule, PeakFrequencyResult

   async def test_hosted_over_the_transport():
       broker = InMemoryTransport()
       host = asyncio.create_task(ModuleHost(PeakFrequencyModule, broker, app="peak-frequency").serve())
       await asyncio.sleep(0)  # let the host subscribe
       with broker.subscribe(PeakFrequencyResult, app="peak-frequency", key="client-1") as results:
           await broker.publish(frame([49.9, 50.1]), app="peak-frequency", key="client-1")
           key, result = await asyncio.wait_for(results.get(), 5)
       await cancel_and_wait(host)
       assert key == "client-1" and result.result.station == "s1"
   ```

   The in-memory transport passes every message through JSON, so a result
   that would not survive Kafka fails here.

For more, see the streamer's tests, beside each module under
`modules/pswamp_modules/`: a chained module (`excursion/tests/`), a batch
query (`range_summary/tests/`), the sources (`sources/tests/`).

### Choose its sources

`pswamp_modules/pipelines/peak_frequency.py` names them in
`<APP>_DATA_CLIENTS`, with a default:

```python
DEFAULT_DATA_CLIENTS = "live:pswamp_modules.sources.live_client:LiveSyntheticClient"
```

- A **live** source is shared: one run, one module instance, results for
  everyone.
- A **recording** (`sample:pswamp_modules.sources.sample_client:SampleRecordingClient`)
  gets a run per client, starting paused, so its page needs the player's
  controls (part 2).

### Watch it run

Restart `./scripts/start-local-hotloaded-pswamp-server.sh` (a new package
needs a rebuild) and open `http://127.0.0.1:8000/peak-frequency`, the
generated page as built into the image. Results arrive at once, from the one
shared live run. From then on, a saved edit under `modules/pswamp_modules/`
reloads the server and restarts the workers.

- **Logs.** The host logs `hosting peak-frequency for peak-frequency: reads
  pmu.frame, publishes peak.frequency.result`, then `instance started for key
  live.live` and `instance dropped for key …`. Under compose they are in
  `docker compose logs module-worker`; in one process, in the server's.
- **The error tray.** A `process` that raises is logged, and an `ErrorEvent`
  goes to the tray of every client watching that run. The module carries on
  with the next input. A `setup` that raises is reported the same way; the
  instance is dropped, and the first input five seconds later builds a new one.
- **Falling behind.** When the module's input queue drops frames, or frames
  arrive more than 2 s after they were sent, it reports on the tray: once on
  falling behind, every 5 s while behind, once on catching up. Tune it with
  `keep_up = KeepUp(max_input_age_s=..., report_every_s=...)`, or
  `keep_up = None` to stay quiet.

## Part 2: The frontend

The generator wrote a web API and a page. How a result gets from the module
to the screen:

```
PeakFrequencyModule           publishes a PeakFrequencyResult on its topic
  → the client's run          keeps the latest: run.latest.get(PeakFrequencyResult)
  → state_message()           builds a PeakFrequencyState                (api.py)
  → /api/peak-frequency/ws    pushes it, on connect and after every change
  → usePeakFrequencySocket()  types it as Wire['PeakFrequencyState']
  → PeakFrequencyPage         renders it
```

State comes down the socket; commands go up as POSTs.
`doc/the-client-server-api.md` explains that seam.

| File | What it holds |
|---|---|
| `app/server-python/src/peak_frequency/api.py` | `REGISTRY` (a run of the pipeline per client), `PeakFrequencyState` and `state_message` (what the socket pushes), the `/ws` endpoint |
| `app/server-python/src/peak_frequency/__init__.py` | what `server.py` picks up: `router`, `lifespan`, and `WS_MESSAGE`, which puts the state model in the api contract |
| `app/client-web/src/pages/peak-frequency/usePeakFrequencySocket.ts` | the socket hook: opens the socket, types its message |
| `app/client-web/src/pages/peak-frequency/PeakFrequencyPage.tsx` | the page |
| `App.tsx`, `components/AppLayout.tsx`, `lib/servers.ts` (in `app/client-web/src/`) | the route, the nav entry, `PEAK_FREQUENCY_WS_PATH` and `PEAK_FREQUENCY_API_PATH` |

### Start the dev loop

Two terminals, the server first:

```
./scripts/start-local-hotloaded-pswamp-server.sh      # the server, Kafka and the workers, on 127.0.0.1:8000
./scripts/start-local-hotloaded-pswamp-web-client.sh  # the web client with hot reload, on http://localhost:5173
```

Open `http://localhost:5173/peak-frequency`. A saved edit to the page shows
at once; a saved edit to `api.py` reloads the server. The api contract is not
reloaded: the next step regenerates it.

### Shape the page's state

`PeakFrequencyState` in `api.py` is the one message the socket carries:

```python
class PeakFrequencyState(BaseModel):
    type: Literal["state"] = "state"
    player: PlayerStatus = Field(description="Which source is open, and where it is.")
    result: PeakFrequencyResult | None = Field(description="The module's latest result; null until the first.")


def state_message(run: PipelineRun) -> PeakFrequencyState:
    return PeakFrequencyState(player=run.player.status(), result=run.latest.get(PeakFrequencyResult))
```

- To show more, add a field and fill it in `state_message`. Another module's
  result is one more `run.latest.get(...)`; the streamer's `state_message`
  carries three.
- Then run `./scripts/generate-api-contract.sh`. It rewrites
  `doc/api/openapi.json` and `app/client-web/src/api/schema.ts`, which the
  page's type comes from. Run it after changing the result body in
  `module.py` too. Commit both files.
- Keep the state a pydantic model. A dict would drop the app out of the
  contract while the page keeps working.
- Nothing warns of a stale contract while you work: the dev client does not
  type-check. `./scripts/error_check.sh` does.

### Change the page

```tsx
export function PeakFrequencyPage() {
  const { state, connected } = usePeakFrequencySocket()
  const result = state?.result?.result
  ...
```

- `state` is `Wire['PeakFrequencyState']`, generated from the Python model.
  The field names are the server's (`frequency_hz`); the hook does not rename
  them.
- `state.result` is the envelope (`timestamp`, `app`), and
  `state.result.result` the body `process` returned.
- `state` is null until the first message, and `result` until the first
  result. Render both cases.
- Components come from `@/components/ui/` (shadcn). What only this page uses
  stays in its folder, imported relatively.
- What the page needs beyond the latest message (the last header, a history)
  is derived in the hook. `usePmuStreamSocket.ts` keeps the last header.
- A control is a POST that becomes a command: "Send it commands", below.
- A page over a recording needs the player's controls (play, pause, step,
  seek). Copy them from the streamer: the POSTs in its `api.py`, the
  functions in `usePmuStreamSocket.ts`, the buttons in
  `PmuTestStreamerPage.tsx`. Give the request bodies names of their own
  (`RollingSeekBody`, not `SeekBody`): two models of one name are both
  renamed in the api contract, the streamer's included.

### Test it

1. **The web API**: `app/server-python/tests/test_peak_frequency.py`, generated.
   The whole server in-process (`TestClient`, in-memory transport, the module
   hosted in the server), a result arriving on the page's socket.

   ```
   ./scripts/run-python-server-tests.sh -k peak_frequency    # this and the module's tests
   ```

   For more, see `app/server-python/tests/test_pmu_test_streamer.py`: POSTs,
   409s, seek and step, two clients on live, a module command, and its
   refusal on the error tray.
2. **The types and the contract**: `./scripts/error_check.sh`. It fails where
   the page reads a field the state no longer has, and while the contract is
   stale.
3. **The page in a browser**: a Playwright spec in `e2e/`, run by
   `./scripts/run-playwright-tests.sh` against the compose stack. The
   generator writes none. The page marks its readout `data-testid="result"`;
   `e2e/pmu-test-streamer.spec.ts` is the example of a page over a pipeline.

## Further recipes

### Send it commands

Three steps: the module, the web API, the page.

**1. The module takes it.** A command is a class beside the module, listed in
`commands`, and applied in `handle`. The streamer's `ExcursionModule` takes
one, which turns its auto-pause on or off:

```python
class AutoPauseCommand(Command):
    version: Literal["v1"] = "v1"
    enabled: bool

class ExcursionModule(Module):
    commands = (AutoPauseCommand,)

    def validate(self, command):          # raise CommandRefused to refuse it
        ...

    async def handle(self, command):      # the returned body is published with its request_id
        self.auto_pause = command.enabled
        return self._state()
```

Test it without the pipeline:
`await module.handle(AutoPauseCommand(enabled=True))`, then `process`.

**2. The web API posts it.** The POST builds the command, and
`dispatch_command` publishes it on its topic under the client's key:

```python
@router.post("/excursion/auto-pause", operation_id="pmu_test_streamer_auto_pause", responses=COMMAND_RESPONSES)
async def auto_pause(client_id: ClientId, body: AutoPauseBody) -> CommandAck:
    return dispatch(AutoPauseCommand(client_id=client_id, enabled=body.enabled))
```

`dispatch` there is `dispatch_command(REGISTRY, command, logger)`. It,
`ClientId`, `CommandAck` and `COMMAND_RESPONSES` come from `shared`.

**3. The page calls it.** Regenerate the contract, then add a function to the
page's hook:

```ts
const setAutoPause = useCallback(
  (enabled: boolean) =>
    fireCommand(
      'pmu-test-streamer',
      postCommand(`${PMU_STREAM_API_PATH}/excursion/auto-pause`, { body: { enabled } }),
    ),
  [],
)
```

`postCommand` is typed against the contract: a wrong path or body is a `tsc`
error. `fireCommand` logs a POST that fails. Disable the control while the
socket is closed, since a POST without a run answers 404. The result arrives
as the next state, not in the POST's answer.

- A module command is checked where the module runs, so the POST answers 200
  when it is accepted, with the command's `request_id`. A refusal comes back
  as an `ErrorEvent` on the tray, carrying that id.
  Player commands are checked before publishing, and a refusal is a 409.
- **A module can command the player** by publishing a player command into the
  sink `setup` gave it. `ExcursionModule` publishes `PauseCommand` when the
  frequency leaves its band.

### Chain it onto another module

A chained module reads another module's results instead of raw frames. Set
its `input_model` to that module's result class, and list both modules in the
pipeline.

The streamer's two frame-rate modules are the example:

- `FrameStatsModule` reads each `PmuFrame` and publishes a `FrameStatsResult`:
  the mean, lowest and highest frequency across the stations at that instant.
- `ExcursionModule` reads each `FrameStatsResult`. It checks whether the mean
  frequency is within ±0.005 Hz of 50 Hz, counts each time it leaves that
  band, and publishes both as an `ExcursionResult`.

```python
class ExcursionModule(Module):
    name = "excursion"
    input_model = FrameStatsResult          # what FrameStatsModule publishes
    output_model = ExcursionResult

    async def process(self, stats: FrameStatsResult) -> Excursion | None:
        mean = stats.result.mean_frequency_hz
        ...

PIPELINE = Pipeline(APP, gateway, modules=(FrameStatsModule, ExcursionModule, ...))
```

So the streamer's data runs frame → frame stats → excursion.

- **The link is a topic.** `FrameStatsModule` publishes on
  `pmu-test-streamer.frame.stats.result`, and `ExcursionModule`'s host reads
  that topic. Neither module holds a reference to the other.
- **So they can run apart**: in one worker, or each in its own.
- **The run key carries through.** A result computed from client 42's frame
  is published under key 42, and the chained module's instance for that
  client reads it.
- **The order in `modules=` does not matter.**
- **Each link is a hop over the transport**, so a chained module sees an
  instant a little later than the module before it.

### Caching and windowed algorithms

Some analyses need several inputs before they can answer: a mean over five
seconds, an estimate of oscillation modes over forty-five. Such a module has
a **window**, and a window brings three problems. The contract has one
declaration for each:

| The problem | The declaration | What it does |
|---|---|---|
| Until the window is full the answer is wrong: a mean over half the window is not the mean it claims to be. | `warm_up_s` | Nothing is published until the window can be full. |
| When the input jumps, the window holds samples from before and after the jump: a window over neither place. | `reset()` | The module is told, and empties its window. |
| So after every seek the page has no result for a full window, even over a part whose results were computed moments ago. | `cache_results` | The server keeps a recording's results and shows them again. |

The two attributes are off unless set, and `reset()` does nothing unless
written. A generated module carries the description of all three, with
`reset()` as a comment to fill in: an empty one would hide from the pipeline
that a windowed module has none. A module that answers from one frame needs
none of them: its result is there with the frame.

The example is `rolling-frequency`
(`modules/pswamp_modules/rolling_frequency/module.py`): the mean frequency
over the last five seconds, on a 30 s recording.

```python
WINDOW_S = 5.0

class RollingFrequencyModule(Module):
    name = "rolling-frequency"
    input_model = PmuFrame
    output_model = RollingFrequencyResult
    warm_up_s = WINDOW_S          # no answer before five seconds of frames are in
    cache_results = True          # the same frames always give the same mean

    def __init__(self) -> None:
        super().__init__()
        self._window: deque[tuple[datetime, float]] = deque()

    def reset(self) -> None:      # the input jumped: the window is about somewhere else
        self._window.clear()

    async def process(self, frame: PmuFrame) -> RollingFrequencyBody | None:
        ...                       # add the frame, drop what is older than 5 s, return the window's mean
```

**1. What each one does.**

- **`warm_up_s`**: how many seconds of unbroken input the analysis needs
  before its answer counts. 0 means every input gives an answer on its own.
  While the module warms up, `process` is still called with every input, so
  it can fill its window, but what it returns is not published. The warm-up
  starts at the module's first input and starts again after every break (see
  `reset`). It is counted in the data's own time, not on the clock.
- **`cache_results`**: set it to `True` to let the server keep this module's
  results for a recording and show them again when any client is at the same
  instant. Setting it is a promise: the same inputs always give the same
  result. So a result depends only on the recording and the instant, never
  on the client, on a command, on the clock, on chance, or on anything else
  outside the inputs. Leave it `False`, the default, for an analysis that is
  not deterministic. Nothing checks this promise: a result kept from an
  earlier replay is shown in place of what the module would have computed
  this time.
- **`reset()`**: called when the input stops being continuous: the player
  moved (a seek, a step back, a loop, another source) or a frame went
  missing. Throw away everything built from earlier inputs, the window above
  all. Keep settings. It is not called before the first input, and a module
  never calls it itself.

**2. What happens around `process`.** `process` is called for every frame.
`Module.run`, in the base class, decides what is published and when `reset()`
is called. With the example's five-second window, and its results kept (4.):
play from the start to 6 s, seek back to 2 s, play on.

| The player | `reset()` | `Module.run` publishes | The page has |
|---|---|---|---|
| plays 0 to 5 s | not called: nothing to throw away yet | nothing: warming up | no result |
| plays 5 to 6 s | | each result, the first for the frame at 5.0 s | the module's result |
| seeks back to 2 s | called, before the frame at 2 s | nothing: warming up again | no result: none was ever computed for 2 s |
| plays 2 to 5 s | | nothing | no result |
| plays 5 to 6 s | | nothing: five seconds after the seek is 7 s | the result kept from the first pass |
| plays 6 to 7 s | | nothing | no result: nobody has computed these |
| plays on from 7 s | | each result | the module's result |

- **The warm-up** starts at the module's first input and is measured between
  frame timestamps: with the first frame at 0 s, the frame at 5.0 s is the
  first whose result is published.
- **A break** is an input from another stream, or a frame missing from the
  sequence. At a break `reset()` is called and the warm-up starts again from
  that input.
- **A stream** is one unbroken pass over a source. A seek, a step back, a
  loop, a switch of source, and playing again after the source failed each
  start a new one. Pausing, a change of speed and stepping forward do not.
- **The module does not look for breaks itself.** Every frame carries its
  stream and its number there (`frame.stream`, `frame.seq`), and `Module.run`
  reads them.
- **Where the page has no result**, the example's says "Window filling".
- **Without a cache** the last column differs after the seek: the page keeps
  the result from before it, from 6 s, until the module's next one at 7 s.

**3. What `cache_results` promises.** That the analysis is deterministic: the
same frames in, the same result out, every time. These break the promise:

- chance: a random start, sampling;
- the clock: `utcnow()`, or doing something every so many seconds of wall
  time;
- anything read from outside the inputs: a file that changes, a service;
- a setting a client can change.

A module like that leaves `cache_results` off. It can still set `warm_up_s`
and write `reset()`: those are about its own results being right, kept or
not. A result that may differ in the last digits of a float from run to run
(threaded linear algebra) is safe to keep, since the kept one is a valid
answer. One that may differ in substance is not.

A pipeline refuses the flag where it can see that the promise cannot hold.
Each is a `ValueError` when the pipeline is declared, so at import:

| The module | The error ends |
|---|---|
| takes commands (lists any in `commands`: "Send it commands") | `sets cache_results, but it takes commands: a command could change what it computes, and cached results are not kept per setting` |
| reads another module's results | `but it does not read frames: without a frame's number, a lost input cannot be told from an unbroken run` |
| has a warm-up and no `reset()` of its own | `but it has a warm-up and no reset(): its window would keep what it held before a seek` |
| shares its result class with another module | `but <Other> publishes <Result> too: a cached result could be either's` |

Whether the analysis is deterministic the pipeline cannot see. That part is
the author's.

**4. Turn the cache on in the web API.** The module allowing it is one half.
The app's runs also need a `ResultCache` to share
(`app/server-python/src/rolling_frequency/api.py`):

```python
_cache: ResultCache | None = None     # made in lifespan, so each server start begins empty

REGISTRY = PipelineRegistry(
    lambda client_id: PipelineRun(client_id, PIPELINE, transport(), cache=_cache)
)

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global _cache
    _cache = ResultCache()
    try:
        async with serve_pipeline(PIPELINE, REGISTRY):
            yield
    finally:
        _cache = None

def state_message(run: PipelineRun) -> RollingFrequencyState:
    result = run.latest.get(RollingFrequencyResult)   # the module's own, or the kept one for the cursor
    return RollingFrequencyState(..., result=result, from_cache=run.from_cache(result))
```

Here `run` is a client's `PipelineRun`, not the module's `run` method.

- **What the page gets.** `run.latest.get(...)` is then the result for the
  instant at the cursor: the module's own, else a kept one, else `None`. It no
  longer shows a result from before a seek. `run.from_cache(result)` says
  which of the two it is, so the page can mark it.
- **What a result is kept under.** The source's name in the app, the result's
  class, and its timestamp: that of the frame it was computed from. Not the
  client: every client's run shares the cache, so one client's results serve
  another's on the same source.
- **How much.** One cache per app, 10 000 results in all by default
  (`ResultCache(max_entries=...)`), the first kept dropped first: 40 to
  60 MB. At one result per frame at 10 Hz that is about 17 minutes.
- **For how long.** It is in the server's memory: empty after a restart.
- **Recordings only.** A live source is never kept.

**5. Test it.** `process` alone tests the analysis. The warm-up and the reset
are `run`'s doing, so test them through `run`, over frames that carry their
place as a gateway stamps it:

```python
from pswamp_core.subscription import Overflow, Subscription

def frame(tenths, hz, stream, seq):      # stream: one unbroken pass; seq: the frame's number in it
    return PmuFrame(mRID="test", timestamp=at(tenths / 10), header=HEADER, values=[hz, hz], stream=stream, seq=seq)

inputs, out = Subscription(_NoOwner(), (PmuFrame,), Overflow.GROW, 0), Recorder()   # a queue that drops nothing
for one in frames:
    inputs.offer(one)
inputs.close()                           # run ends once it has read them all
await RollingFrequencyModule().run(inputs, out)
out.published                            # what a host would send on
```

`rolling_frequency/tests/test_module.py` has three such tests: nothing is
published before five seconds, a seek starts the window over, and so does a
missing frame. Its first lines hold the helpers used here (`at`, `HEADER`,
`Recorder`, `_NoOwner`). Frames built without `stream` and `seq` count as one unbroken
run.

**6. What to watch for.**

- **An analysis that is not deterministic must not be kept**, and nothing but
  its author can tell.
- **A window that drops samples by age** keeps the later ones after a seek
  back, for good, unless `reset()` clears it.
- **A module that cannot keep up publishes nothing.** Its queue drops old
  frames, every drop is a break, and the warm-up starts again. It says so on
  the error tray ("Keeping up" in `doc/server-data-architecture.md`).
- **A frame lost elsewhere is not reported.** One dropped by a broker starts
  the window over just the same, with nothing on the error tray.
- **What a module publishes itself**, through the sink it was given in
  `setup` (a command to the player, say), is not held back during the
  warm-up. Only what `process` returns is.
- **The cache computes nothing.** An instant nobody has played still waits
  for the window.
- **The warm-up is in the data's time.** At 2× it takes half as long on the
  clock.

### Read data yourself: a batch query

A module that sets `reads_gateway = True` gets `self.gateway` (a gateway over
the pipeline's sources, of its own) before `setup`. It can answer a command by
reading a range:

```python
async for frame in await self.gateway.consume(start, end): ...
```

`RangeSummaryModule` is the example: command-only (`input_model = None`). The
worker hosting it needs the app's `<APP>_DATA_CLIENTS`, and the settings of
the clients that names (`REMOTE_URL`, ...), since it builds the gateway itself.

### Run it in its own worker

A worker is the server's image running `python -m pswamp_core.worker`. It
hosts the modules named in `PSWAMP_WORKER_MODULES`, from the pipelines named
in `PSWAMP_WORKER_PIPELINES`. The generator put `peak-frequency` in the shared
`module-worker`, beside the streamer's modules. To give it a process of its
own:

**1. Add a worker that hosts only it.** In `docker-compose.yml`:

```yaml
  peak-frequency-worker:
    build: .
    image: p-swamp:latest
    command: ["python", "-m", "pswamp_core.worker"]
    working_dir: /workspace/p-SWAMP/modules      # outside the server's src/
    environment:
      <<: *transport
      PSWAMP_WORKER_PIPELINES: "pswamp_modules.pipelines.peak_frequency:PIPELINE"
      PSWAMP_WORKER_MODULES: "peak-frequency"
    depends_on:
      kafka:
        condition: service_healthy
    restart: unless-stopped
    cpus: 1.0
    mem_limit: 512m
    develop: *worker-watch       # defined on module-worker, so place this after it
```

In `k8s/p-swamp-local.yaml`, copy the `p-swamp-module-worker` Deployment,
rename it (`metadata.name`, every `app:` label, the container), and set the
same two variables:

```yaml
          env:
            - name: PSWAMP_TRANSPORT
              value: kafka:pswamp_core.transport.kafka:KafkaTransport
            - name: KAFKA_BOOTSTRAP_SERVERS
              value: p-swamp-kafka:9092
            - name: PSWAMP_WORKER_PIPELINES
              value: pswamp_modules.pipelines.peak_frequency:PIPELINE
            - name: PSWAMP_WORKER_MODULES
              value: peak-frequency
          resources:
            requests:              # what the scheduler reserves for the pod
              cpu: "100m"
              memory: "192Mi"
            limits:                # the most it may use
              cpu: "1"
              memory: "512Mi"
```

`doc/server-data-architecture.md` ("A module in a worker of its own") has a
whole Deployment to copy.

**2. Take it out of the shared worker.** Remove `peak-frequency` from
`module-worker`'s `PSWAMP_WORKER_MODULES` (and its pipeline from
`PSWAMP_WORKER_PIPELINES`), in compose and in k8s. A module named in two
workers is run by both: every result arrives twice.

**3. Apply it.** `docker compose up -d` (or restart
`./scripts/start-local-hotloaded-pswamp-server.sh`), or `kubectl apply -f
k8s/p-swamp-local.yaml`. The image, the module, its web API and its page are
unchanged. The new worker logs `hosting peak-frequency for peak-frequency: …`.

A module that reads the gateway also needs its sources there: the app's
`<APP>_DATA_CLIENTS` and the settings of the clients it names. The streamer's
`batch-worker`, which hosts `range-summary`, is the example.

### Scale it

What a worker of its own lets you change, for that module alone:

- **More memory.** Raise `resources.limits.memory` (k8s) or `mem_limit`
  (compose). A worker rests at about 30 MB. On top of that comes the module's
  own state, once per run key: one instance per client on a recording, one in
  total on a live source. A pod that passes its limit is killed and restarted;
  its instances are rebuilt on the next input, without what they had counted.
- **More CPU.** Raise `resources.limits.cpu` or `cpus`. A module's `process`
  runs on one event loop, so more than one core helps only an analysis moved
  off the loop ("A CPU-heavy module", below).
- **Isolation.** A slow or crashing module stalls or restarts its own worker
  and nothing else. The server, the pages and every module not chained onto
  it carry on; its own results stop until it is back.
- **Its own node or schedule.** It is an ordinary Deployment, so
  `nodeSelector`, priorities and the rest apply to it alone.

What it does not let you change yet: **the number of replicas**. Keep
`replicas: 1` for each worker. Topics have one partition and workers no
consumer group, so two replicas would each read every input and publish every
result twice. A module scales up, not out.

### A CPU-heavy module

`process` runs on the worker's event loop, so a slow one stalls every other
module in that process.
- Give it a worker of its own, with a CPU limit.
- Run the analysis off the loop: `await asyncio.to_thread(analyse, ...)`, or a
  `ProcessPoolExecutor` for pure-Python work.
- With numpy or scipy in a pool, set `OPENBLAS_NUM_THREADS=1`: BLAS's own
  threads per call multiply the CPU and collapse throughput.
- Watch the tray: falling behind is reported.

### Plug in a data source

- **Your own store, over HTTP:** implement
  `doc/remote-data-integration-contract.md` and name `RemoteDataClient` in
  `<APP>_DATA_CLIENTS` with `REMOTE_URL`. Nothing in this repo changes.
- **In Python:** subclass `DataClient` (`kind = "history"` or `"live"`,
  `coverage`, `consume`, `env_settings`), prove it with
  `pswamp_core.testing.DataClientConformance`, put the package in the image,
  and name it in `<APP>_DATA_CLIENTS`. `sample_client.py` and `live_client.py`
  in `modules/pswamp_modules/sources/` are the examples.

## When it does not work

| Symptom | Likely cause |
|---|---|
| The page shows no result, and the server logs nothing about the module | No host for it. With Kafka, the module is not in any worker's `PSWAMP_WORKER_PIPELINES`/`PSWAMP_WORKER_MODULES`. |
| Results arrive twice as often | Two workers host the same module. |
| A result field never reaches the page | The contract is stale: run `./scripts/generate-api-contract.sh`. |
| A POST answers 404 | The page's socket is not open: a command never builds a run. |
| A module command does nothing | It was refused where the module runs: see the tray, or the worker's log. |
| The worker exits with code 2 | No broker (`PSWAMP_TRANSPORT` unset: the server hosts modules then), or nothing to host. |
| Tests or builds fail oddly | Docker's disk is full: `docker system df`. |
