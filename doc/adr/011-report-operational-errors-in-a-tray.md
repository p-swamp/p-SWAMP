# ADR-011: Report operational failures on an error topic, shown in a tray on every page

- Status: Accepted
- Date: 2026-10-19

> Written up after it was built, from PR #13. The date is when that pull
> request merged.

## Context

Once modules run in other processes
([ADR-007](007-connect-modules-over-a-pub-sub-transport.md)) and commands are
acknowledged when accepted
([ADR-010](010-address-commands-by-class-acknowledge-on-acceptance.md)), things
fail where the person affected cannot see them. A module refuses a command after
its 200. A module's `process` raises in a worker. A source's provider fails. A
module falls behind and its queue drops input. A recording has a gap. The logs
record all of it, but the person watching the run never reads a worker's log.

## Decision

We will publish each operational failure as an `ErrorEvent`
(`models/src/pswamp_models/common/errors.py`) on the app's error topic,
`<app>.error.event`, under its run's key. It carries the `request_id` of the
command it answers, if any.

- The `errors` app (`app/server-python/src/errors/`) receives events from every
  app's error topic. It pushes each one to the clients watching that run: the
  run's own client, or every follower of a shared live run.
- `<ErrorTray>` (`app/client-web/src/components/ErrorTray.tsx`) shows them on
  every page, from `/api/errors/ws`.
- A failure that a run could not publish at all (an undelivered command, or an
  error report itself) goes straight to the tray, because the error topic is on
  that same transport.
- A module falling behind (`KeepUpMonitor`, `core/src/pswamp_core/keep_up.py`)
  and a gap in a recording are reported the same way, rate-limited.

## Consequences

- When a module refuses a command, the person who sent it hears about it.
- Under load, dropping stale input is still the right policy for a live stream,
  and it is no longer silent.
- The log line stays the source of truth. A notice is a copy addressed to the
  person whose run it was.
- An error notice is not a grid alarm. An alarm is a module's normal result,
  and stays one.
- The tray keeps the last 20 notices per client id for the life of the
  process.

## Alternatives considered

- **Logs only.** Free, and invisible to the person watching the run.
- **An error field in each app's state message.** Every app would repeat the
  same plumbing, and a worker could reach the state message only through the
  transport anyway.
- **The grid monitor's alarm path.** Alarms are domain results, which an
  operator acknowledges and annotates. Infrastructure failures would put "a
  worker cannot keep up" in the operator's alarm list.
