# ADR-012: Read a deployment's history through a small HTTP contract; p-SWAMP stores nothing

- Status: Accepted
- Date: 2026-10-19

> Written up after it was built, from PR #13. The date is when that pull
> request merged.

## Context

Deployments (RNDP, a TSO's own cluster) keep their PMU history in stores that
p-SWAMP does not choose. The teams integrating those stores work outside this
repo, on whatever stack they have. The web stack is stateless on purpose: it
has no database and no volume. A history source must be able to seek, read a
range, and read a year of data without holding it in memory.

## Decision

We will read a deployment's history through a **remote data service** that the
deployment runs in front of its own store. The service is specified in HTTP
terms alone, in `doc/remote-data-integration-contract.md`:

- `GET /v1/coverage` says what range the service holds.
- `POST /v1/queries` asks for at most `limit` records in a range. The records
  come back as that call's streamed response, one JSON line per record
  (`pmu.frame`), closed by an `end` line.
- The connection that asks is the one that answers, and closing it cancels the
  query.

p-SWAMP's client is `RemoteHistory` (`modules/remote-history/`), a playable
history source like any other. It reads a long range page by page inside its
`aread`, so the player sees one stream. In compose and k8s, `remote-data-stub`
serves a year of synthetic history over the same contract.

## Consequences

- The deployment chooses which store answers. p-SWAMP never sees the store's
  schema or location, and the repo stores nothing.
- The contract needs no correlation ids, no second channel and no cancel route,
  and the open connection gives backpressure for free.
- A command never reaches the service. It stops at the player, which seeks, or
  at a module, which reads a range from its own sources.
- The contract is preliminary. Not settled yet: authentication and TLS, limits
  on concurrent queries and rate, models beyond `pmu.frame` and how their
  schema changes, and the readiness of the store behind the service.
- Live data from a deployment is a different contract, a live `SourceModule`
  over its feed, not this one.

## Alternatives considered

- **p-SWAMP owns a time-series store.** There would be one schema to write
  against, but it ends the stateless rule, and every deployment already has a
  store.
- **One source per store product** (InfluxDB, TimescaleDB, …) in this repo.
  p-SWAMP would have to track every vendor's driver and schema, and each
  deployment's store would leak into the repo.
- **A query over REST, with the records returned over Kafka.** This was the
  earlier design. It needs correlation ids, a cancel route and a broker on the
  deployment's side, to do what one HTTP response does.
- **gRPC or Arrow Flight.** Typed and fast, but every service would then need
  a code generator and its toolchain. NDJSON over HTTP needs neither.
