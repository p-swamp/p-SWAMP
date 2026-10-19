# ADR-008: Make every message a versioned pydantic model, sent as JSON

- Status: Accepted
- Date: 2026-10-19

> Written up after it was built, from PR #13. The date is when that pull
> request merged.

## Context

A pipeline's messages cross three boundaries: a topic between processes, a
socket to the browser, and the api contract
([ADR-003](003-use-openapi-contract-for-client-server-api.md)) that the
client's types are generated from. The desktop package pickles Python objects
(numpy arrays, UUIDs, datetimes) onto Kafka. Only Python can read them, nothing
validates them, and the web layer has to write an adapter for each page. In the
new stack several teams produce and consume messages, in workers that may run
different builds.

## Decision

We will make every message a `DataModel`
(`models/src/pswamp_models/common/data_model.py`): a pydantic model with a
pinned schema `version` (`Literal["v1"]`), an optional `mRID` and a UTC
`timestamp`.

- Its JSON is the whole codec, on every topic and every socket:
  `model_dump_json` out, `model_validate_json` in. No dicts, numpy or pickle
  cross a topic or a socket.
- Its topic is derived from its class name (`PmuFrame` → `pmu.frame`), and a
  topic carries exactly one class. `subscribe` and `Pipeline` refuse a second
  class with the same topic.
- Every frame carries its channel layout (`PmuHeader`), so a frame can be read
  on its own.
- The classes live in `pswamp-models`
  ([ADR-005](005-workspace-models-modules-cli.md)).

## Consequences

- A message can be logged, validated on receipt, and published in
  `doc/api/openapi.json` with no adapter. A page's types come from the same
  classes as a module's.
- A payload with another version fails validation instead of being half read.
- The message classes are the topic catalogue, so renaming a class renames its
  topic.
- JSON frames are large: every frame repeats its header, and nothing is
  batched. Cheaper frames (the header once per layout, producer batching) are
  not built.
- Not decided here: how a message changes within a version. Today pydantic
  ignores unknown fields, so adding an optional field within `v1` does not
  break an older reader. But no test or check holds that, and the api contract
  check covers only the classes that ride in socket messages.

## Alternatives considered

- **Pickle**, as the desktop package uses. There is no schema to write, but it
  is Python-only, unvalidated, and unsafe to load from a broker that other
  processes write to.
- **Avro or protobuf with a schema registry.** Compact, with enforced evolution
  rules, but it adds a second schema language beside pydantic and the OpenAPI
  contract, and a registry to run.
- **A binary encoding for frames only** (msgpack, Arrow). Worth it if frame
  size becomes the bottleneck. Until then, one codec everywhere is simpler.
