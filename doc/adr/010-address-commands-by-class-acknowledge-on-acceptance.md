# ADR-010: Address a command by its class, and acknowledge it on acceptance

- Status: Accepted
- Date: 2026-10-19

> Written up after it was built, from PR #13. The date is when that pull
> request merged.

## Context

The client-server api sends commands up as POSTs and state down the socket, and
a command's reply, `CommandAck`, never carries state
([ADR-003](003-use-openapi-contract-for-client-server-api.md),
`doc/the-client-server-api.md`). Now that modules run in other processes
([ADR-007](007-connect-modules-over-a-pub-sub-transport.md)), a POST can no
longer know when it answers whether a module command worked: the module may be
in a worker, behind a broker that is down. Commands also no longer come only
from the browser: a module can pause the player (auto-pause). And a command
that lands late is worse than one that fails, such as a pause applied a minute
after the click.

## Decision

We will make a command a message
([ADR-008](008-make-every-message-a-versioned-json-model.md)) whose class is its
address.

- Each command class has exactly one receiver in a pipeline: the run's
  `ActiveSource` router (the player commands and `SwitchSourceCommand`) or one
  module. `Pipeline` refuses a second receiver. Anyone may publish a command,
  and anyone may watch it.
- A command travels on its own topic, `<app>.<command>`, under the run's key,
  whether the web API or a module sent it.
- The router runs beside the web API, so a player command is validated before
  it is published, and a refusal is the POST's 409. A module command is
  validated where the module runs, and a refusal is an `ErrorEvent`
  ([ADR-011](011-report-operational-errors-in-a-tray.md)).
- A 200 means **accepted**: the command is queued for its receiver.
  `CommandAck` carries the command's `request_id`, and so does whatever answers
  or refuses it.
- A command is applied within `CONTROL_DEADLINE_S` (10 s) of being issued, or
  reported. The outbox gives up on a command it cannot send by then, and the
  receiver refuses one older than that.

## Consequences

- A module command can fail after its 200. The browser hears about it only
  through the error tray, which every page shows.
- A broker outage, or a slow command ahead in the queue, never makes a command
  land long after its click.
- A module can command the player exactly as a page does.
- A command that never reaches its receiver (its worker is not running, say)
  is lost with only a log line. The ack and every answer carry the
  `request_id` a watchdog would match on, but no watchdog is built.

## Alternatives considered

- **A verb and a dict** on one generic endpoint. There is nothing to declare,
  but nothing is validated or published in the contract, and nothing says who
  handles the command.
- **Hold the POST until the module answers.** A 200 would then mean *applied*,
  but every request would wait on a broker round trip and another process, and
  would time out exactly when the broker is down.
- **Answer with the new state.** That gives state two paths, with an order to
  reconcile between them. The api keeps one.
