# ADR-013: Put a CIM reference id on each frame, never grid data

- Status: Accepted
- Date: 2026-10-14

> Written up after it was built. The date is when the scope was decided.

## Context

Modules will need grid (CIM) data for what a frame measures: which line a
current channel belongs to, or which part of the topology a frequency comes
from. A CIM team works on the lookup separately from the module, transport and
source work, and none of those should wait on it. The frame is the message
every module reads, at 50 Hz. Grid data on it would cost kilobytes per frame
and tie every message to the shape of the CIM model.

## Decision

We will add one optional field, `PmuHeader.cimReferenceId`: an id for the grid
data that applies to the frame.

- The `SourceSet` sets it, through `CimReferenceEnricher`
  (`core/src/pswamp_core/enrich.py`), on every record its streams yield, before
  any module sees the record.
- `reference_for(header)` decides the id once per channel layout, and the result
  is cached. A frame that already carries an id passes through unchanged.
- Today `reference_for` is a stub that returns one configured id
  (`[enrich] cim_reference` in the pipeline file, overridden by
  `<APP>_CIM_REFERENCE`). A real lookup overrides `reference_for`, and nothing
  else changes.
- Grid data itself never travels on the transport. A module that needs it looks
  it up by the id.

## Consequences

- Every module, in any process, sees the same id, decided once and early, with
  no configuration of its own.
- The frame stays small.
- A module that needs grid data must resolve the id itself, and nothing to do
  that is built yet.
- Open:
  - How a lookup is installed. Today `CimReferenceEnricher` is hard-coded.
  - What a lookup receives. Today it gets the layout only: no stream, no
    source, no time. So a recording made before a grid change cannot get the
    old model's id.
  - Whether a lookup may do I/O, and what happens when it fails. Today it is
    synchronous on the event loop, and a lookup that raises stops the stream.
  - How long an id holds. Today it is per layout, for the life of the run.
  - Whether there is one id per layout or one per column.

## Alternatives considered

- **Grid data on the header.** This was an earlier design, filled in by
  enrichers. Frames would be self-contained, but each would carry kilobytes,
  and every reader would be tied to the grid model's shape.
- **Each module looks up what it needs.** No shared hook is needed, but every
  module repeats the lookup, and modules may disagree about which model
  applies.
- **A lookup service on the transport.** That puts a round trip in the frame
  path, for an answer that changes once per layout.
