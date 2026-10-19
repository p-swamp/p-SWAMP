"""The CIM graph: the grid as loaded, the PMU Analogs, the store and its readers."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("lazycim")

from lazycim import CIMRepository, F, L  # noqa: E402

from pswamp_core.cim import (  # noqa: E402
    SAMPLE_GRID,
    CimSettings,
    GraphVersion,
    LocalStore,
    Store,
    analog_index,
    analog_name,
    analog_table,
    connect_reader,
    model_id,
    open_store,
    prepare,
    refresh_expired,
    stage,
)
from pswamp_core.cim.grid import NAMESPACE_ALIASES  # noqa: E402

SETTINGS = CimSettings(cim_path=SAMPLE_GRID)
COUPLER = "3f5e0000-0000-4000-8000-000000000034"  # Beta's bus coupler, closed in the sample grid
LINE = "3f5e0000-0000-4000-8000-000000000024"  # Alpha-Beta, a line of the sample grid
EQ_MODEL = "3f5e0000-0000-4000-8000-000000000001"


@pytest.fixture(scope="module")
def grid():
    loaded = stage(SETTINGS)
    if not loaded.writable:
        pytest.skip("the CGMES vocabularies are not available to LazyCIM")
    return loaded


@pytest.fixture
def store(grid):
    """A store of the test's own, filled with the sample grid."""
    fresh = Store(SETTINGS, LocalStore())
    fresh.fill()
    return fresh


def writer(store: Store) -> CIMRepository:
    from lazycim.demo import CIM100

    return CIMRepository(
        store.writer_backend(), default_namespace=CIM100, graphs=store.layout, namespace_aliases=NAMESPACE_ALIASES
    )


def test_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("PSWAMP_CIM_URL", "http://oxigraph:7878/")
    monkeypatch.setenv("PSWAMP_CIM_PATH", "/grid")
    settings = CimSettings.from_env()
    assert (settings.url, settings.cim_path) == ("http://oxigraph:7878", Path("/grid"))


def test_the_analog_naming_rule():
    assert analog_name("Beta", 400.0, "V") == "PMU_Beta_400_V"
    assert analog_name("HELSINKI", 420, "F") == "PMU_HELSINKI_420_F"
    assert analog_name("Alpha", 400, "I", "Alpha-Beta 400 kV line") == "PMU_Alpha_400_I_Alpha-Beta_400_kV_line"
    assert analog_name(" OSLO ", 132.5, "V") == "PMU_OSLO_132.5_V"


def test_the_grid_is_staged_one_profile_per_graph(grid):
    for keyword in ("EQ", "SSH", "TP", "SV", "GL", "DY", "OP"):
        assert len(grid.graphs[f"cgmes:model:{keyword}"]) > 0, keyword
    assert "cgmes:schema:OP" in grid.graphs
    assert grid.model_id == EQ_MODEL


def test_the_grid_gets_a_v_and_an_f_per_voltage_level_and_an_i_per_line_end(store):
    reader = connect_reader(store=store)
    table = analog_table(reader)
    assert sorted(table[table.quantity == "V"].name) == [
        "PMU_Alpha_400_V", "PMU_Beta_400_V", "PMU_Gamma_132_V", "PMU_Gamma_400_V",
    ]  # fmt: skip
    assert len(table[table.quantity == "F"]) == 4
    currents = table[table.quantity == "I"]
    assert len(currents) == 6 and set(currents.sequence) == {1, 2}
    assert "PMU_Alpha_400_I_Alpha-Beta_400_kV_line" in set(currents.name)
    assert table.mRID.is_unique and table.node.notna().all()


def test_a_reader_finds_every_analog_in_one_query(store):
    reader = connect_reader(store=store)
    analog_index(reader)  # the schema of what it reads is discovered once per repository
    with reader.measure() as work:
        index = analog_index(reader)
    assert len(index) == 14 and work.queries <= 2


def test_a_reader_never_commits(store):
    reader = connect_reader(store=store)
    reader.from_mRID(COUPLER).open = True
    with pytest.raises(PermissionError):
        reader.commit()


def test_the_store_says_which_grid_it_holds(store):
    assert model_id(store) == EQ_MODEL


def test_an_edit_is_one_update_into_the_ssh_graph_that_moves_the_version_stamp(store):
    edit = writer(store)
    switch = edit.from_mRID(COUPLER)
    before = store.version()
    switch.open = True
    with edit.measure() as work:
        edit.commit()
    assert work.write_calls == 1 and store.version() == before + 1  # in that one update
    held = store.backend.dataset.graph(_iri("cgmes:model:SSH"))
    assert any(str(o) == "true" and COUPLER in str(s) for s, _, o in held)


def test_a_reader_reads_again_only_when_the_stamp_moved(store):
    reader = connect_reader(store=store)
    watch = GraphVersion(store)
    assert reader.from_mRID(COUPLER).open is False
    assert watch.changed() is False
    time.sleep(0.3)  # nothing expires on a timer
    with reader.measure() as work:
        assert reader.from_mRID(COUPLER).open is False
    assert work.queries == 0
    edit = writer(store)
    edit.from_mRID(COUPLER).open = True
    edit.commit()
    assert reader.from_mRID(COUPLER).open is False  # what it read, until told
    assert watch.changed() is True and watch.changed() is False
    refresh_expired(reader)
    assert reader.from_mRID(COUPLER).open is True


def test_the_stamp_is_one_tiny_query(store):
    watch = GraphVersion(store)
    calls = []
    real = store.backend.execute
    store.backend.execute = lambda query: calls.append(query) or real(query)
    try:
        watch.changed()
    finally:
        store.backend.execute = real
    assert len(calls) == 1 and "urn:pswamp:version" in calls[0]


def test_equipment_is_read_once(store):
    reader = connect_reader(store=store)
    line = reader.from_mRID(LINE)
    assert line.r > 0
    refresh_expired(reader)  # the graph changed: what changes is read again, equipment is not
    with reader.measure() as work:
        assert line.r > 0
    assert work.queries == 0


def test_a_reset_is_one_update_that_puts_the_ssh_profile_back(store):
    edit = writer(store)
    edit.from_mRID(COUPLER).open = True
    edit.commit()
    stamped = store.version()
    store.reset()
    assert store.version() == stamped + 1
    fresh = connect_reader(store=store)
    assert fresh.from_mRID(COUPLER).open is False
    assert len(analog_index(fresh)) == 14  # the Analogs are part of the grid


def test_a_store_is_filled_once(store):
    assert store.loaded() and store.fill() is False


def test_a_reader_waits_for_a_grid(grid):
    empty = Store(SETTINGS, LocalStore())
    with pytest.raises(TimeoutError):
        connect_reader(store=empty, timeout=0.2)


def test_a_folder_with_no_grid_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match="not a folder of CGMES"):
        stage(CimSettings(cim_path=tmp_path))


def _iri(name):
    from rdflib import URIRef

    return URIRef(name)


def test_a_switch_s_state_reads_through_the_layout(store):
    reader = connect_reader(store=store)
    table = reader.query(L.Breakers).to_dataframe(mRID=F.mRID, open=F.open)
    assert len(table) > 0 and set(table.open) <= {True, False}


# A store p-SWAMP did not load: any LazyCIM backend, filled by its owner.


def _their_store() -> LocalStore:
    """A backend factory, as a script would give one (top level, so it pickles): a store filled
    with the sample grid by someone else, whose writer does not stamp."""
    backend = LocalStore("theirs")
    Store(SETTINGS, backend).fill()
    backend.update("DROP SILENT GRAPH <urn:pswamp:meta>")
    return backend


THEIRS = CimSettings(backend=_their_store)


def test_a_backend_s_store_is_read_and_never_loaded_reset_or_written(grid):
    store = open_store(THEIRS)
    assert not store.owned and store.version() == 0
    reader = connect_reader(THEIRS, timeout=5)
    assert len(analog_table(reader)) > 0
    for doing in (store.fill, store.reset, store.writer_backend):
        with pytest.raises(PermissionError, match="did not load"):
            doing()


def test_a_store_without_a_stamp_is_said_to_change_every_so_often(grid):
    version = GraphVersion(open_store(THEIRS), unstamped_every=0.05)
    assert not version.changed()
    time.sleep(0.06)
    assert version.changed() and not version.changed()


def test_a_stamp_that_appears_is_followed_instead(store):
    store.backend.update("DROP SILENT GRAPH <urn:pswamp:meta>")
    version = GraphVersion(store, unstamped_every=3600)
    assert not version.changed()
    edit = writer(store)
    edit.from_mRID(COUPLER).open = True
    edit.commit()
    assert version.changed() and not version.changed()


def test_a_module_reads_the_repository_a_script_hands_it(store):
    from pswamp_core.modules import Module

    class ReadsTheGrid(Module):
        name = "reads-the-grid"
        cim = True

    module = ReadsTheGrid()
    repo = CIMRepository(store.backend, graphs="discover", namespace_aliases=NAMESPACE_ALIASES)
    module.cim_repo = repo
    assert module.cim_repo is repo
    assert module.cim_version.store.backend is store.backend and not module.cim_version.store.owned


def test_prepare_leaves_a_grid_that_has_its_analogs_alone(store):
    repo = CIMRepository(store.backend, graphs="discover", namespace_aliases=NAMESPACE_ALIASES)
    before = store.version()
    assert prepare(repo) == 0 and store.version() == before


def test_prepare_gives_a_grid_its_dynamics_and_analogs_in_graphs_it_lacks(store):
    """As a LazyCIM demo model in a store of a script's own: no Dynamics or Operation data graph."""
    for keyword in ("DY", "OP"):
        store.backend.dataset.remove_graph(_iri(f"cgmes:model:{keyword}"))
    repo = CIMRepository(store.backend, graphs="discover", namespace_aliases=NAMESPACE_ALIASES)
    assert prepare(repo) == len(analog_table(connect_reader(store=store))) > 0
    machines = connect_reader(store=store).query(L.SynchronousMachineTimeConstantReactances).count()
    assert machines > 0 and prepare(repo) == 0


def _model_of(settings: CimSettings) -> str | None:
    return model_id(open_store(settings))


def test_a_backend_factory_opens_its_store_in_a_child_process(grid):
    import multiprocessing

    with multiprocessing.get_context("spawn").Pool(1) as pool:
        assert pool.apply(_model_of, (THEIRS,)) == EQ_MODEL
