# ADR-007: Connect modules over a replaceable pub/sub transport, with Kafka between processes

- Status: Accepted
- Date: 2026-10-19

> Written up after it was built, from PR #13. The date is when that pull
> request merged.

## Context

Analysis modules are written by several teams, and some are heavy (mode
estimation, islanding). A slow or crashing one must not stall the others or the
page, and a heavy one needs CPU and memory limits of its own. The same modules
must also run in one process: in a unit test, in CI's bare `docker run`, on a
laptop with no broker. The desktop package's apps talk to Kafka directly, so
there, where an app runs and what it is written against are the same thing.
Until this change the web stack was one process with no broker.

## Decision

We will connect a pipeline's parts through a `Transport`: keyed
publish/subscribe, one topic per message class per app (`<app>.<message
class>`), and the run's key on every record. A module never sees it; a
`ModuleHost` subscribes and publishes for it.

- `PSWAMP_TRANSPORT` picks the implementation. Unset, it is the
  `InMemoryTransport`, and the server hosts every module itself. Set to
  `KafkaTransport`, the server and one or more workers
  (`python -m pswamp_core.worker`, the same image) share a broker, and each
  worker hosts the modules named by `PSWAMP_WORKER_PIPELINES` and
  `PSWAMP_WORKER_MODULES`. Where a module runs is configuration, never code.
- The in-memory transport round-trips every message through JSON and holds a
  topic to one class, so a message that would not survive Kafka fails in a unit
  test.
- Kafka is the first broker because the desktop package and the deployments we
  target already run it. Topics have one partition and about a minute of
  retention (`LIVE_TOPIC_CONFIGS`); workers have no consumer group, and the
  local broker has no volume.
- A run publishes through an `Outbox`. When it is full, it drops the oldest
  *data* message, never a command, an answer to one, or an error.

## Consequences

- A heavy module gets its own process and limits through an edit to compose or
  k8s, not to its code or its page.
- Compose and k8s now run a broker and two workers (`module-worker`,
  `batch-worker`) beside the server. The stack stays stateless: Kafka is a
  transport, not a store, and nothing on it survives a restart.
- With one partition and no consumer group, each worker runs one replica. A
  second replica would answer every frame twice, so a module scales up, not
  out, until topics are partitioned.
- Another broker (NATS, say) is one `Transport` subclass that passes
  `core/tests/transport_suite.py` and is named in `PSWAMP_TRANSPORT`. No
  module, pipeline, web API or page changes.
- Every worker runs the server's image, web backend included. A slimmer worker
  image is possible, since a worker imports only models, core and modules, but
  none is built.
- Sources are not hosted on the transport; they run in their run's process
  ([ADR-005](005-workspace-models-modules-cli.md),
  [ADR-006](006-make-a-source-a-module.md)).

## Alternatives considered

- **Modules talk to Kafka themselves**, as the desktop apps do. There is no
  abstraction to maintain, but every module would carry a broker client and its
  settings, could not run in a test without a broker, and could not move between
  processes without a code change.
- **NATS as the first broker.** Lighter to run, and the transport keeps it one
  class away. We chose Kafka because the deployments already operate it.
- **HTTP or gRPC calls between modules.** Request and reply suit a query, not a
  50 Hz stream fanned out to several consumers, and every module would become a
  server with an address.
- **One process, no workers.** Simplest, but one slow module stalls everything,
  and no module can have limits of its own.
- **Planning and branching streams**: a "service manager" that stitches
  recorded and live data, or forks a stream between pipelines. Deferred: for
  now a pipeline is a flat list of modules over one active source.
