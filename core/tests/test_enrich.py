"""The CIM reference stub: stamped once per layout, on every frame a source set yields."""

from __future__ import annotations

from support import HEADER, ListSource, Measurement, frame

from pswamp_core.enrich import CimReferenceEnricher
from pswamp_core.sources import SourceSet


def test_the_reference_is_set_on_the_header_and_shared_per_layout():
    enricher = CimReferenceEnricher("grid-1")
    a, b = enricher.enrich(frame(0)), enricher.enrich(frame(1))
    assert a.header.cimReferenceId == "grid-1"
    assert a.header is b.header and a.header.header_id == HEADER.header_id
    assert frame(0).header.cimReferenceId is None  # the provider's frame is untouched


def test_no_reference_and_other_messages_pass_unchanged():
    original = frame(0)
    assert CimReferenceEnricher(None).enrich(original) is original
    message = Measurement(value=1)
    assert CimReferenceEnricher("grid-1").enrich(message) is message
    stamped = CimReferenceEnricher("first").enrich(original)
    assert CimReferenceEnricher("second").enrich(stamped).header.cimReferenceId == "first"


async def test_every_frame_through_the_source_set_is_enriched():
    sources = SourceSet([ListSource()], enrichers=[CimReferenceEnricher("grid-1")])
    frames = [f async for f in await sources.consume()]
    assert frames and all(f.header.cimReferenceId == "grid-1" for f in frames)
