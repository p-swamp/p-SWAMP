"""The CIM graph in a real Oxigraph server: filled, edited by one writer, seen by a reader once its
SSH profile expires, and reset, with what each step costs. Opt in with a throwaway server, whose
store this empties::

    podman run --rm -p 7878:7878 ghcr.io/oxigraph/oxigraph:0.5.2 serve --bind 0.0.0.0:7878 --union-default-graph
    PSWAMP_TEST_CIM_URL=http://<host>:7878 uv run pswamp test server -k oxigraph -s

(On Windows under podman, ``<host>`` is the VM's IP, not localhost, which adds tens of milliseconds
to every request.)"""

from __future__ import annotations

import os
import time

import pytest

pytest.importorskip("lazycim")

from lazycim import CIMRepository  # noqa: E402
from lazycim.demo import CIM100  # noqa: E402

from pswamp_core.cim import (  # noqa: E402
    SAMPLE_GRID,
    CimSettings,
    GraphVersion,
    analog_index,
    connect_reader,
    model_id,
    refresh_expired,
    stage,
)
from pswamp_core.cim.grid import NAMESPACE_ALIASES  # noqa: E402
from pswamp_core.cim.store import Store, _remote  # noqa: E402

URL = os.environ.get("PSWAMP_TEST_CIM_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not URL, reason="PSWAMP_TEST_CIM_URL names no Oxigraph server")

COUPLER = "3f5e0000-0000-4000-8000-000000000034"


@pytest.fixture(scope="module")
def store():
    settings = CimSettings(url=URL, cim_path=SAMPLE_GRID)
    if not stage(settings).writable:
        pytest.skip("the CGMES vocabularies are not available to LazyCIM")
    remote = Store(settings, _remote(URL))
    remote.backend.update("CLEAR ALL")
    started = time.perf_counter()
    assert remote.fill() is True
    print(f"\nfill: {time.perf_counter() - started:.2f} s")
    return remote


def test_a_reader_sees_the_grid_and_its_analogs(store):
    reader = connect_reader(store=store)
    assert model_id(store) == "3f5e0000-0000-4000-8000-000000000001"
    analog_index(reader)
    started = time.perf_counter()
    with reader.measure() as work:
        assert len(analog_index(reader)) == 14
    print(f"analog index: {work.queries} queries, {1000 * (time.perf_counter() - started):.1f} ms")


def test_one_writer_one_update_and_a_reader_sees_it_once_the_stamp_moved(store):
    writer = CIMRepository(store.writer_backend(), default_namespace=CIM100, graphs=store.layout, namespace_aliases=NAMESPACE_ALIASES)
    reader = connect_reader(store=store)
    watch = GraphVersion(store)
    switch = writer.from_mRID(COUPLER)
    assert reader.from_mRID(COUPLER).open is False
    switch.open = True
    started = time.perf_counter()
    with writer.measure() as work:
        writer.commit()
    print(f"commit: {work.write_calls} update, {1000 * (time.perf_counter() - started):.1f} ms")
    assert work.write_calls == 1
    started = time.perf_counter()
    assert watch.changed() is True
    print(f"stamp: {1000 * (time.perf_counter() - started):.1f} ms")
    refresh_expired(reader)
    started = time.perf_counter()
    with reader.measure() as work:
        assert reader.from_mRID(COUPLER).open is True
    print(f"reader re-read: {work.queries} queries, {1000 * (time.perf_counter() - started):.1f} ms")
    store.reset()
    assert watch.changed() is True
    refresh_expired(reader)
    assert reader.from_mRID(COUPLER).open is False
