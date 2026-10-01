# Module cookbook

How to add an analysis module to the server data architecture, show its
results on a page, send it commands, and run it in a process of its own.
`doc/server-data-architecture.md` explains the pieces; this is the recipe.

The examples come from two apps:
- **`peak-frequency`**: what the generator writes below. One module, one page.
- **The PMU test streamer** (`app/server-python/src/pmu_test_streamer/`): the
  reference example, with three modules. `FrameStatsModule` computes each
  frame's statistics, `ExcursionModule` watches those statistics for the
  frequency leaving its band, and `RangeSummaryModule` summarizes a time range
  of a recording on command.

## The pieces you touch

| File | What it holds |
|---|---|
| `<pkg>/<pkg>_module.py` | the module: what it reads, what it publishes, `process` (and `handle`) |
| `<pkg>/pipeline.py` | the pipeline: the app's name, its sources, its modules |
| `<pkg>/api.py` | the web API: the run registry, the socket's state message, the POSTs |
| `app/client-web/src/pages/<slug>/` | the page and its socket hook |
| `app/server-python/tests/test_<pkg>.py` | the tests |
| `docker-compose.yml`, `k8s/p-swamp-local.yaml` | which worker hosts the module |

## Add a module and its page

**1. Generate it.**

```
./scripts/generate-new-module-with-frontend.sh peak-frequency "Peak frequency"
```

This writes a working app and registers it everywhere:
- a module over PMU frames with a placeholder analysis: the station with the
  highest frequency;
- its `pipeline.py` (sources: the synthetic live feed) and `api.py`;
- a page at `/peak-frequency` showing the latest result;
- unit tests;
- entries in `server.py`, the route table, the nav, `lib/servers.ts`, and the
  module-worker's lists in compose and k8s.

It regenerates the api contract and runs `error_check.sh`. Restart
`./scripts/start-local-hotloaded-pswamp-server.sh` (a new package needs a
rebuild) and open the page: results arrive at once, from the one shared live
run.

**2. Write the analysis.** In `peak_frequency_module.py`, replace
`highest_frequency` and the result body it fills. Keep the analysis a plain
function and `process` a thin adapter: the function is then testable with plain
values.

```python
class PeakFrequencyModule(Module):
    name = "peak-frequency"                 # its identity in results, logs and the tray
    input_model = PmuFrame                  # what it reads
    output_model = PeakFrequencyResult      # a ResultEnvelope subclass: what it publishes

    async def process(self, frame: PmuFrame) -> PeakFrequencyBody | None:
        columns = frame.header.columns(measurement="f")     # the layout rides in every frame
        ...                                                 # return None to publish nothing
```

- The layout is in `frame.header`. A module that derives something from it
  (column indexes) re-derives it when `frame.header.header_id` changes; the
  streamer's `stats_module.py` does.
- The CIM reference for the frame is `frame.header.cimReferenceId`.
- A result class is a `ResultEnvelope[Body]` subclass with
  `version: Literal["v1"] = "v1"`. Its name is its topic
  (`PeakFrequencyResult` → `peak.frequency.result`), and the browser's type is
  generated from it.

**3. Choose its sources.** `pipeline.py` names them in
`<APP>_DATA_CLIENTS`, with a default:

```python
DEFAULT_DATA_CLIENTS = "live:pmu_test_streamer.live_client:LiveSyntheticClient"
```

- A **live** source is shared: one run, one module instance, results for
  everyone.
- A **recording** (`sample:pmu_test_streamer.sample_client:SampleRecordingClient`)
  gets a run per client, starting paused, so the page needs the player's
  controls. Copy them from the streamer's page and api.

**4. Shape the page's state.** `api.py`'s state model is what the socket
pushes. Add fields to it, then run `./scripts/generate-api-contract.sh`. The
page reads the generated type (`Wire['PeakFrequencyState']`), field names and
all.

## Test it

```
./scripts/run-python-server-tests.sh -k peak_frequency
```

The generated tests show the three levels:
1. **the analysis**: call the function with plain values;
2. **the module**: `await PeakFrequencyModule().process(frame)` with a
   hand-made `PmuFrame`;
3. **the page's socket**: the whole server in-process (`TestClient`, in-memory
   transport, the module hosted in the server), a result arriving on the socket.

For more, see `app/server-python/tests/test_pmu_test_streamer.py`: POSTs, 409s,
seek and step, two clients on live, a module command, and its refusal on the
error tray.

## See what it is doing

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

## Send it commands

A command is a class beside the module, listed in `commands`, and applied in
`handle`. The streamer's `ExcursionModule` takes one, which turns its
auto-pause on or off:

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

The POST builds it, and `dispatch_command` publishes it on its topic under the
client's key:

```python
@router.post("/excursion/auto-pause", operation_id="pmu_test_streamer_auto_pause", responses=COMMAND_RESPONSES)
async def auto_pause(client_id: ClientId, body: AutoPauseBody) -> CommandAck:
    return dispatch(AutoPauseCommand(client_id=client_id, enabled=body.enabled))
```

- The page calls it with `postCommand` from its hook.
- A module command is checked where the module runs, so the POST answers 200
  when it is accepted, with the command's `request_id`. A refusal comes back
  as an `ErrorEvent` on the tray, carrying that id.
  Player commands are checked before publishing, and a refusal is a 409.
- **A module can command the player** by publishing a player command into the
  sink `setup` gave it. `ExcursionModule` publishes `PauseCommand` when the
  frequency leaves its band.

## Chain it onto another module

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

## Read data yourself: a batch query

A module that sets `reads_gateway = True` gets `self.gateway` (a gateway over
the pipeline's sources, of its own) before `setup`. It can answer a command by
reading a range:

```python
async for frame in await self.gateway.consume(start, end): ...
```

`RangeSummaryModule` is the example: command-only (`input_model = None`). The
worker hosting it needs the app's `<APP>_DATA_CLIENTS`, and the settings of
the clients that names (`REMOTE_URL`, ...), since it builds the gateway itself.

## Run it in its own worker

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
    environment:
      <<: *transport
      PSWAMP_WORKER_PIPELINES: "peak_frequency.pipeline:PIPELINE"
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
              value: peak_frequency.pipeline:PIPELINE
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

## Scale it

What a worker of its own lets you change, for that module alone:

- **More memory.** Raise `resources.limits.memory` (k8s) or `mem_limit`
  (compose). A worker rests at about 70 MB. On top of that comes the module's
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

## A CPU-heavy module

`process` runs on the worker's event loop, so a slow one stalls every other
module in that process.
- Give it a worker of its own, with a CPU limit.
- Run the analysis off the loop: `await asyncio.to_thread(analyse, ...)`, or a
  `ProcessPoolExecutor` for pure-Python work.
- With numpy or scipy in a pool, set `OPENBLAS_NUM_THREADS=1`: BLAS's own
  threads per call multiply the CPU and collapse throughput.
- Watch the tray: falling behind is reported.

## Plug in a data source

- **Your own store, over HTTP:** implement
  `doc/remote-data-integration-contract.md` and name `RemoteDataClient` in
  `<APP>_DATA_CLIENTS` with `REMOTE_URL`. Nothing in this repo changes.
- **In Python:** subclass `DataClient` (`kind = "history"` or `"live"`,
  `coverage`, `consume`, `env_settings`), prove it with
  `pswamp_core.testing.DataClientConformance`, put the package in the image,
  and name it in `<APP>_DATA_CLIENTS`. `sample_client.py` and `live_client.py`
  are the examples.

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
