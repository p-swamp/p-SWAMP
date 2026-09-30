# The server data architecture

How PMU data gets from a source, through analysis modules, to the browser, and
how a command gets back up. The shared pieces live in `core/` (the
`pswamp_core` package). The PMU test streamer (`/pmu-test-streamer`) is the
worked example of every piece.

## What it has to do

- Take PMU data from several kinds of source: a recording, a live feed, or a
  remote data service run by the deployment.
- Pass it through swappable analysis **modules**, each with a clear contract
  for what it reads and what it publishes, and on to the web frontend.
- Let a module run in the server or in a process of its own (a pod, a compose
  service), so a heavy module cannot stall the rest.
- Declare a **pipeline**: its sources and the modules that process them.
- Carry messages over topics behind a **transport** interface. Kafka is the
  default; replacing it (with NATS, say) means adding one class.
- Send typed **commands** upstream from any part, handled by the part that
  declares them.
- Add a CIM reference to each frame early, so any module can look up grid
  data.
- Share a live pipeline between every viewer. Give each client (browser, by
  client id) its own replay of recorded data.
- Run the same way in compose, in minikube, and in a cloud cluster.

## Vocabulary

| Term | Meaning |
|---|---|
| message | A pydantic model with a schema version. Everything that crosses a topic, a socket or a process boundary is one. |
| `PmuFrame` | One instant of every channel in a stream, carrying its channel layout (`PmuHeader`). |
| provider (`DataClient`) | One source of data: a *history* (seekable) or a *live* feed (tailed from now). |
| gateway | A pipeline's providers as named sources, one of them active. Enriches every frame on the way out. |
| player | Paces the active source: replays a history in real time or tails a live feed. Owns the transport controls. |
| transport | Keyed publish/subscribe: in-memory in one process, or Kafka between processes. |
| topic | `<app>.<message class>`, e.g. `pmu-test-streamer.pmu.frame`. One class per topic. |
| key | Which pipeline run a record belongs to: a client id, or `live.<source>`. |
| module | Reads one message class, publishes a result class, and may answer commands. |
| host / worker | A host runs one module instance per key. A worker is a process that runs hosts. |
| pipeline | The declaration: an app's sources and modules. |
| run | One running pipeline under one key: a gateway, a player, and the latest message of each class. |
| edge | The app's FastAPI package: POSTs become commands, and the socket pushes state. |
| command | A typed message going upstream. Its class decides who handles it. |

## The picture

```
DATA DOWN    provider → gateway (enrich) → player → topic <app>.pmu.frame → module → topic <app>.<result>
             → the run's latest → edge → socket → browser
COMMANDS UP  browser → POST → edge → topic <app>.<command> → player | module
             a module may publish a command too
WHERE        in-memory transport: modules hosted in the server; Kafka: modules in workers
```

```mermaid
flowchart TB
    classDef data fill:#e8f1fb,stroke:#3b6ea5,color:#000
    classDef edge fill:#eeeeee,stroke:#555,color:#000

    sources["Providers<br/>recording · live feed · remote data service"]:::data
    subgraph run["Run: one per client for a recording, one per live source"]
        direction TB
        gw["Gateway<br/>named sources, one active · CIM reference"]:::data
        player["Player<br/>replay or tail"]:::data
        latest["latest<br/>newest message of each class"]:::data
    end
    subgraph transport["Transport: in-memory or Kafka"]
        direction LR
        frames[["&lt;app&gt;.pmu.frame"]]
        results[["&lt;app&gt;.&lt;result&gt;"]]
        commands[["&lt;app&gt;.&lt;command&gt;"]]
    end
    host["Module host<br/>one instance per key<br/>in the server or a worker"]:::data
    edge["Edge (FastAPI)"]:::edge
    browser(["Browser"]):::edge

    sources ==> gw ==> player ==> frames ==> host ==> results ==> latest
    player ==> latest ==> edge ==>|"state"| browser

    browser -.->|"POST"| edge -.-> commands
    host -.->|"a module may command"| commands
    commands -.-> player
    commands -.-> host
```

Thick arrows carry data and dotted arrows carry commands. Every arrow carries a
message, and the browser's TypeScript types are generated from the same
classes.

## Per client and shared

| | Recorded source | Live source |
|---|---|---|
| run key | the client id | `live.<source>` |
| runs | one per client, with its own cursor and speed | one per live source, always on |
| player controls | play, pause, step, seek, speed | none: a live feed is tailed |
| modules | one instance per client | one instance, results shared |

A client picks its source with a command. A client on a live source follows the
live run's topics instead of opening a stream of its own. Topics are shared by
every key of an app; the record key keeps runs apart.

## Where it runs

With no transport configured, the server uses the in-memory transport and
hosts the modules itself: one container, no broker. Tests and CI use this
mode. In compose and k8s, the server and one or more workers share a Kafka
broker, and each worker hosts the modules it is told to. The code path is the
same in both; only the transport differs.

## The pieces

Each piece gets its Why and Where when its code lands.

### Messages
*What.* Every message is a `DataModel`: a pydantic model with a pinned schema
`version`, an optional `mRID` and a UTC `timestamp`. Its topic is its class
name (`PmuFrame` → `pmu.frame`).

```python
class FrameStats(BaseModel):
    mean_hz: float

class FrameStatsResult(ResultEnvelope[FrameStats]):   # topic frame.stats.result
    version: Literal["v1"] = "v1"

FrameStatsResult.model_validate_json(text)           # the whole codec
```

| Message | Carries |
|---|---|
| `PmuFrame` | One instant of every channel, with its `PmuHeader` (station, channel, measurement and unit per column, data rate, `cimReferenceId`, `header_id`). |
| `Command` | An upstream action. The player's are `Play`, `Pause`, `Step`, `Seek`, `Speed` and `SwitchSource`; a module declares its own. |
| `PlayerStatus` | The player's mode, source, cursor, speed and what it can do. |
| `ResultEnvelope[T]` | A module's result body `T`, with the module's identity and the command it answers, if any. |
| `ErrorEvent` | An operational failure, for the person using the run. |
| `PipelineClosed` | A run stopped; hosts drop its module instances. |

*Why.* One codec from provider to browser. A message can be logged,
validated on receipt, and published in the browser's api contract without an
adapter. A pinned version makes an incompatible payload fail loudly. Every
frame carries its layout, so a module needs nothing but the frame in hand.

*Where.* `core/src/pswamp_core/messages/`.

### Transport
*What.* Keyed publish/subscribe: **one topic per message class, per app, and
the run's key on every record**.

```python
await transport.publish(frame, app="pmu-test-streamer", key="42")   # topic pmu-test-streamer.pmu.frame
with transport.subscribe(FrameStatsResult, app="pmu-test-streamer", key="42") as results:
    async for key, result in results: ...                          # key "42" only
with transport.subscribe(PmuFrame, app="pmu-test-streamer") as frames:
    async for key, frame in frames: ...                            # every key: a module host's view
```

The deployment picks the implementation with `PSWAMP_TRANSPORT`
(`name:module.path:Class`, plus that name's `{NAME}_{SETTING}` variables).
Unset, it is the `InMemoryTransport`. The player and modules publish
synchronously into an `Outbox`, which sends in order and, when full, drops the
oldest data message, but never a command or an error.

*Why.*
- **One mechanism.** A module is always reached over the transport, so "in
  the server" and "in a worker" are two transports, not two code paths.
- **The in-memory transport behaves like a broker.** Every message goes
  through JSON, and a topic carries one exact class. A message that would not
  survive Kafka fails in a unit test.
- **Replaceable.** A new transport implements `publish` (and `_watch` for
  incoming topics) and passes `core/tests/transport_suite.py`.
- **A transport is not a data source.** It carries what is published, in
  order, and keeps nothing for late subscribers.

**Kafka.** `KafkaTransport` (`kafka:pswamp_core.transport.kafka:KafkaTransport`
with `KAFKA_BOOTSTRAP_SERVERS`) creates each topic with one partition and
about a minute of retention. It reads every topic its process listens to with
one consumer, from the topic's end, with no consumer group. Compose runs the
broker as `kafka` (Apache Kafka, one KRaft node, no volume).

*Where.* `core/src/pswamp_core/transport/`, `subscription.py`, `settings.py`
(spec loading, shared with the data providers); `core/tests/transport_suite.py`
(run against the compose broker with
`KAFKA_TEST_BOOTSTRAP_SERVERS=127.0.0.1:19092`).

### Modules
*What.* A module reads one message class and publishes a result class; it may
also answer commands.

```python
class FrameStatsModule(Module):
    name = "frame-stats"
    input_model = PmuFrame
    output_model = FrameStatsResult            # a ResultEnvelope subclass

    async def process(self, frame: PmuFrame) -> FrameStats | None: ...
```

A module that answers commands lists their concrete classes in `commands`
and implements `handle`, and `validate` if it can refuse one. What `handle`
returns is published like a `process` result, carrying the command's
`request_id`. A refusal or failure is published as an `ErrorEvent` carrying it
too.

A `ModuleHost` runs a module. It subscribes to the module's input and command
topics for every key, and builds one instance per run key on that key's first
message. It drops the instance when the run publishes `PipelineClosed`, or
after five minutes with nothing for it.

*Why.* A contributor writes the analysis and three class attributes. The
module never sees the transport: it reads a queue and publishes into a sink.
That lets the same module run in the server or in a worker. Reading the layout
off `frame.header` means it needs no configuration. `process` runs on the
event loop; a CPU-heavy module runs its analysis in a thread or process pool.

*Where.* `core/src/pswamp_core/modules.py`, `host.py`, `command_routing.py`;
the example is `app/server-python/src/pmu_test_streamer/stats_module.py`.

### Gateway and providers
*What.* A provider implements `DataClient`: it is a `history` (it holds a
range, reports it as `coverage`, and yields any part of it) or a `live` feed
(it yields records as they arrive). A `DataGateway` holds a run's providers as
named sources, one of them active.

```python
class SampleRecordingClient(DataClient):
    kind = "history"
    async def coverage(self): return self.recording.coverage          # [first, end)
    async def consume(self, time_range):
        for frame in self.recording.frames:
            if time_range.contains(frame.timestamp):
                yield frame

gateway = DataGateway([SampleRecordingClient("sample"), LiveClient("live")])
gateway.switch("live")                            # only an explicit switch changes the source
stream = await gateway.consume(start=t0)          # a seek
chunk = await gateway.consume(start=t0, end=t1)   # exactly [t0, t1)
```

*Why.* A provider is written against the contract alone, so a deployment can
write its own outside this repo. `pswamp_core.testing.DataClientConformance`
is the executable contract: inherit it, supply the client, and pytest checks
it. With one source active at a time, a stream always has exactly one provider
behind it. "Jump to a time" and "query a chunk" are the same call. The gateway
opens a client on first use, so a source nobody reads costs nothing. History
lives with the provider: the repo stores nothing.

**Configured, not coded.** An app's sources come from `<APP>_DATA_CLIENTS`,
with a default in the app's `pipeline.py`. Each client reads its own
`{NAME}_{SETTING}` variables:

```
PMU_TEST_STREAMER_DATA_CLIENTS=sample:pmu_test_streamer.sample_client:SampleRecordingClient,live:acme.pmu:KafkaFeed
LIVE_BOOTSTRAP_SERVERS=kafka.acme:9092
```

A deployment plugs in its own provider with one package in the image and one
variable.

*Where.* `core/src/pswamp_core/datagateway/`, `settings.py`, `testing.py`;
the examples are `app/server-python/src/pmu_test_streamer/sample_client.py`
(history) and `live_client.py` (live: the sample re-stamped on the wall clock).

### CIM reference
*What.* The gateway sets an optional `PmuHeader.cimReferenceId` on every
frame: an id for the grid (CIM) data that applies to it. Enrichers passed to a
`DataGateway` run on every record its streams yield. `CimReferenceEnricher`
decides the reference once per layout. **It is a stub**: it returns one
configured id (`PMU_TEST_STREAMER_CIM_REFERENCE`, default `n44-cim-stub`,
`none` for none). A lookup against a CIM model overrides `reference_for` and
nothing else changes.

*Why.* Every reader's frames pass through the gateway, so every module sees
the same reference, decided once, early. It travels with the frame, so a module
in a worker gets it with no configuration of its own. It is a reference, not
the grid data itself, which would cost kilobytes per frame.

*Where.* `core/src/pswamp_core/datagateway/enrich.py`; wired in
`pmu_test_streamer/pipeline.py`.

### Player
Paces the active source. Checks its commands before they are published, so a
refusal is the POST's 409.

### Pipelines and runs
The declaration of an app's sources and modules, the run built from it per
key, and the registry that caps and evicts runs.

### Commands
A command's class is its address; exactly one part declares it. Anyone may
publish it; anyone may subscribe to watch it.

### The edge
What an app's `api.py` keeps once the core does the rest: the state message it
pushes, and the POSTs that build commands.

### Errors
`ErrorEvent`: an operational failure (a provider, a module, a refused module
command), shown on every page's error tray.

### Keeping up
A module or publisher that falls behind reports it instead of dropping data
silently.

### Remote data
A REST contract a deployment implements in front of its own store; p-SWAMP
reads it as one more provider.

### Deployment
Compose, minikube, and what a cloud cluster changes.

## Not here yet

- The grid monitor on the core (it still runs its own `Hub`/`Bus` in
  `pswamp_web/`).
- More than one replica of a worker.
- A NATS transport.
- A live run over a real feed.
