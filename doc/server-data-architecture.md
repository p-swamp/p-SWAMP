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
A module declares its input class, its result class and any commands it
answers, and implements `process`. A host runs it; the module never sees the
transport.

### Gateway and providers
The provider contract a data source implements, and the gateway that holds a
run's providers as named sources.

### CIM reference
The gateway stamps each frame's layout with a reference to the grid (CIM) data
that applies to it.

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
