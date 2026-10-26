# ADR-015: Let a pipeline relay another pipeline's live run instead of starting the feed again

- Status: Proposed
- Date: 2026-10-20

## Context

ADR-009 gives a live source one shared run, started with its app and keyed
`live.<source>`. The run belongs to the pipeline that lists the source: topics are
`<app>.<topic>`, so two pipelines listing the same live source start the feed twice,
each on topics of its own. For a cheap feed that is nothing; for a live simulation
(a process of its own at 50 frames/s) or for analysis already computed on a feed, a
second app would pay again for what is running.

## Decision

We will let a source of one pipeline take what it needs from another pipeline's live
run:

```toml
[[sources]]
name = "live-pmu"
from = "pmu-pipeline"                  # pipelines/pmu-pipeline.toml
get  = ["pmu", "frame-stats"]          # its live source, and modules running on it
```

- Each name in `get` is a source or a module of that pipeline: exactly one live
  source (its frames are the new source's primary output) and any modules whose
  results are wanted. In `<APP>_SOURCES` it is `name:@pmu-pipeline/pmu+frame-stats`.
- It is a live `SourceModule` (`pswamp_core.relay.RelaySource`): it subscribes to
  those classes on the owner's topics under `live.<source>` and yields them. The
  pipeline's own run publishes them under its own key like any live feed, and its
  modules read them like any other input; no re-stamping of run ids or streams.
- A run hands its transport to its sources (`SourceModule.bind`), which only a relay uses.
- A pipeline takes at most one producer per class: a class produced by a relayed
  source and by one of its modules is refused. `source_models` counts every class a
  source declares, not only the first.

## Consequences

- The feed, and whatever the owner computed on it, run once. Each pipeline still has
  its own module instances and settings over what it relays.
- Live data only: the owner's `live.<source>` is the one key with a single run to
  follow. A recording is per client and cannot be relayed.
- One hop: a relay of a relay is refused, which also rules out cycles.
- The owner must be started first (a subscriber hears only what is published after it
  subscribes); the server's `APPS` order decides that. A pipeline file needs the
  owner's file beside it, and the owner's modules installed.
- A relayed module result is the owner's answer for the owner's frame, not aligned
  with this pipeline's own processing, and this pipeline cannot command the owner's modules.
- Only the first output is the run's frame. A client run that follows the relayed
  live run subscribes to that class and the pipeline's own results; the other relayed
  classes reach the live run, and the modules that read them.
- A new transport hop for what is relayed (through the transport, even in one process).

## Alternatives considered

- **A process-wide registry that dedupes equal sources.** Implicit; two files that
  happen to name the same source would silently share a run and its settings.
- **Following the owner's run from a client run.** The pipeline's modules are hosted
  on its own topics and would never see the owner's frames.
- **Merging the two apps into one pipeline.** Loses separate module sets, settings
  and topic namespaces, which is what separate apps are for.
