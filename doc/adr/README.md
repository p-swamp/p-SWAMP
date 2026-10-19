# Architecture Decision Records

Short notes recording an architectural decision, why we made it, and what it
costs. One decision per file.

An ADR is a record of a moment, not documentation of the current system. Once
merged it is not edited — if we change our minds we write a new ADR and mark the
old one superseded, so the reasoning survives the decision. For how the system
works *now*, read `AGENTS.md` and the rest of `doc/`.

**Writing one:** copy `template.md`, name it `NNN-<decision>.md` with the next
free number (`003-use-openapi-contract-for-client-server-api.md`), keep it to a
page, and open a pull request like any other change.

**When:** a choice that is expensive to reverse, cuts across sub-teams, or would
make a newcomer ask "why on earth is it like this?". Everyday choices inside one
team's own code do not need one.

## Index

| ADR | Decision |
|---|---|
| [001](001-record-architecture-decisions.md) | Record architecture decisions |
| [002](002-use-python-backend-with-typescript-frontend.md) | Use a Python backend with a TypeScript frontend |
| [003](003-use-openapi-contract-for-client-server-api.md) | Use an OpenAPI contract for the client-server api |
| [004](004-use-a-monorepo.md) | Keep the project in a single monorepo |
| [005](005-workspace-models-modules-cli.md) | One uv workspace of models, module projects and a CLI |
| [006](006-make-a-source-a-module.md) | Make a source a `Module` subclass, still run in its run's process |
| [007](007-connect-modules-over-a-pub-sub-transport.md) | Connect modules over a replaceable pub/sub transport, with Kafka between processes |
| [008](008-make-every-message-a-versioned-json-model.md) | Make every message a versioned pydantic model, sent as JSON |
| [009](009-run-recordings-per-client-and-live-sources-shared.md) | Give each client its own run of a recording, and share one run per live source |
| [010](010-address-commands-by-class-acknowledge-on-acceptance.md) | Address a command by its class, and acknowledge it on acceptance |
| [011](011-report-operational-errors-in-a-tray.md) | Report operational failures on an error topic, shown in a tray on every page |
| [012](012-read-history-through-a-remote-data-contract.md) | Read a deployment's history through a small HTTP contract; p-SWAMP stores nothing |
| [013](013-put-a-cim-reference-id-on-each-frame.md) | Put a CIM reference id on each frame, never grid data |
