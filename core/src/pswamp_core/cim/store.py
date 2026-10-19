# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The store that holds the CIM graph, and how to read it.

**One writer, many readers.** The store is filled and edited by one process,
the web backend; everything else reads it, each reader through a repository of
its own (``connect_reader``) that refuses to commit, and keeps what it has read.

**A version stamp says when the graph changed.** One triple in a graph of its own
(``urn:pswamp:meta``) counts the writes: the writer's backend
(``Store.writer_backend``) adds its increment to the very update of each commit,
so the stamp and the edit are seen together or not at all, and a fill and a reset
move it too. A reader asks for it (``GraphVersion.changed``: one tiny query) and,
only when it moved, marks what it holds of the steady-state hypothesis and the
state variables stale (``refresh_expired``) and reads again. Nothing expires on a
timer, so a reader that finds nothing new has read nothing else. A module does none of
this itself: the core does it for its repository before each call (``watch``).

The store is an **Oxigraph** server (``PSWAMP_CIM_URL``), spoken to through LazyCIM's
``OxigraphServerBackend`` (SPARQL 1.1 queries and updates, and the graph store to fill it), or, when that is unset, a ``LocalStore`` in the process: the same
named graphs and the same SPARQL, over an rdflib dataset. Either way a commit is
one SPARQL update, which the store applies as a transaction.
"""

from __future__ import annotations

import re
import threading
import time

import requests

from lazycim import CachePolicy, CIMRepository, GraphDBBackend, GraphLayout
from lazycim.backends._sparql import SparqlProtocolBackend
from lazycim.backends.oxigraph_server import OxigraphServerBackend  # needs requests only, not pyoxigraph
from lazycim.backends.memory import result_to_sparql_json
from lazycim.demo import CIM100
from rdflib import Dataset, Graph, URIRef

from ..log import get_logger
from .grid import _FULL_MODEL, NAMESPACE_ALIASES, Grid, model_graph, stage
from .settings import CimSettings

__all__ = [
    "LocalStore",
    "ReadOnlyRepository",
    "Store",
    "connect_reader",
    "GraphVersion",
    "model_id",
    "refresh_expired",
    "open_store",
]

logger = get_logger("pswamp_core.cim")

#: The data graphs a writer writes to. A store holds the ones the grid has; a new value
#: goes to its profile's graph, which the store creates on the first write.
PROFILES = ("EQ", "SSH", "TP", "SV", "GL", "OP", "DY")
#: What a store that is not up yet raises.
_UNREACHABLE = (requests.ConnectionError, requests.Timeout)
#: The version stamp: one triple, in a graph of its own.
META_GRAPH = "urn:pswamp:meta"
_STAMP = "<urn:pswamp:cim> <urn:pswamp:version>"
#: The update that moves the stamp on, from nothing to 1.
_BUMP = (
    f"DELETE {{ GRAPH <{META_GRAPH}> {{ {_STAMP} ?old }} }} "
    f"INSERT {{ GRAPH <{META_GRAPH}> {{ {_STAMP} ?new }} }} "
    f"WHERE {{ OPTIONAL {{ GRAPH <{META_GRAPH}> {{ {_STAMP} ?old }} }} BIND(COALESCE(?old, 0) + 1 AS ?new) }}"
)
#: A query's dataset clause, ``FROM <g>`` or ``FROM NAMED <g>``.
_DATASET_CLAUSE = re.compile(r"\bFROM\s+(?:NAMED\s+)?<[^>]*>")


class LocalStore(GraphDBBackend):
    """An in-process SPARQL store with named graphs, where reads see every graph merged.

    It is a ``GraphDBBackend`` whose two calls to a server (a query, an update) go to an
    rdflib dataset instead, so a repository over it writes exactly as it would to
    Oxigraph. Thread-safe: the dataset is not, so every call holds a lock."""

    def __init__(self, name: str = "local", *, over: LocalStore | None = None) -> None:
        """A new store, or, ``over`` another, a second handle on its dataset (and its lock)."""
        super().__init__(f"local://{name}", name=name)
        self.dataset = over.dataset if over is not None else Dataset(default_union=True)
        self._lock = over._lock if over is not None else threading.RLock()

    def execute(self, query: str):
        # A FROM clause makes rdflib copy each graph it names into a new default graph, on every
        # query: a second for the vocabularies alone. The default graph here already is every graph
        # merged, and data and vocabularies never share a subject, so the clauses are dropped.
        query = _DATASET_CLAUSE.sub("", query)
        with self._lock:
            return result_to_sparql_json(self.dataset.query(query))

    def _update(self, sparql: str) -> None:
        with self._lock:
            self.dataset.update(sparql)

    def namespaces(self) -> dict[str, str]:
        return {}

    def put(self, name: str, graph: Graph, *, replace: bool = False) -> None:
        """Add ``graph`` to the named graph ``name`` (emptied first with ``replace``), in one step.

        What filling a store with SPARQL does, without parsing it: rdflib takes minutes to read
        an update the size of a grid."""
        with self._lock:
            target = self.dataset.graph(URIRef(name))
            if replace:
                target.remove((None, None, None))
            target += graph


def _remote(url: str, kind: type[OxigraphServerBackend] = OxigraphServerBackend) -> OxigraphServerBackend:
    """Oxigraph: queries at ``/query``, updates at ``/update``, the graph store at ``/store``."""
    return kind(url, name="oxigraph")


class _Stamping:
    """A backend whose every update also moves the version stamp on, in the same request."""

    def _update(self, sparql: str) -> None:
        super()._update(f"{sparql} ;\n{_BUMP}")  # type: ignore[misc]


class _StampingLocal(_Stamping, LocalStore):
    pass


class _StampingRemote(_Stamping, OxigraphServerBackend):
    pass


class ReadOnlyRepository(CIMRepository):
    """A reader's repository: everything a ``CIMRepository`` reads, and no commit."""

    def commit(self) -> None:
        raise PermissionError("this repository reads the CIM graph; only the web backend writes it")


class Store:
    """The graph's store, as one process sees it: ``backend``, and what is loaded into it."""

    def __init__(self, settings: CimSettings, backend: SparqlProtocolBackend) -> None:
        self.settings = settings
        self.backend = backend

    @property
    def grid(self) -> Grid:
        """The grid as loaded (what ``fill`` writes and ``reset`` restores)."""
        return stage(self.settings)

    @property
    def layout(self) -> GraphLayout:
        """The writer's graph layout: every profile's data graph, and the grid's vocabularies."""
        schema = [name.removeprefix("cgmes:schema:") for name in self.grid.graphs if name.startswith("cgmes:schema:")]
        return GraphLayout(
            model={keyword: model_graph(keyword) for keyword in PROFILES},
            schema={keyword: f"cgmes:schema:{keyword}" for keyword in schema},
        )

    def writer_backend(self) -> SparqlProtocolBackend:
        """A backend over this store whose every update also moves the version stamp: the writer's."""
        if isinstance(self.backend, LocalStore):
            return _StampingLocal("writer", over=self.backend)
        return _remote(self.settings.url, _StampingRemote)

    def version(self) -> int:
        """The version stamp: how many times the graph was written (0 before it is filled)."""
        found = self.backend.execute(f"SELECT ?v WHERE {{ GRAPH <{META_GRAPH}> {{ {_STAMP} ?v }} }}")
        bindings = found["results"]["bindings"]
        return int(bindings[0]["v"]["value"]) if bindings else 0

    def loaded(self) -> bool:
        """Whether the store holds a grid (its EQ graph has anything in it)."""
        found = self.backend.execute(f"SELECT ?s WHERE {{ GRAPH <{model_graph('EQ')}> {{ ?s ?p ?o }} }} LIMIT 1")
        return bool(found["results"]["bindings"])

    def reachable(self) -> bool:
        """Whether the store answers (a server that is still starting does not)."""
        try:
            self.loaded()
        except _UNREACHABLE:
            return False
        return True

    def fill(self, timeout: float = 120.0) -> bool:
        """Write the grid into an empty store; leave a filled one alone. Whether it wrote. Waits up to
        ``timeout`` seconds for a store that does not answer yet."""
        deadline, pause = time.monotonic() + timeout, 0.1
        while not self.reachable():
            if time.monotonic() > deadline:
                raise TimeoutError(f"{self.backend.name} did not answer in {timeout:.0f} s")
            time.sleep(pause)
            pause = min(pause * 2, 2.0)
        if self.loaded():
            return False
        grid = self.grid
        started = time.monotonic()
        # EQ last: it is what ``loaded`` looks for, so a reader never starts on half a grid.
        names = sorted(grid.graphs, key=lambda name: name == model_graph("EQ"))
        for name in names:
            self._put(name, grid.graphs[name])
        self.backend.update(_BUMP)
        logger.info("loaded %d triples into %s in %.1f s", grid.triples(), self.backend.name, time.monotonic() - started)
        return True

    def reset(self) -> None:
        """Put the steady-state hypothesis back as it was loaded (every switch, terminal and set
        point the grid has been operated through), in one update."""
        name = model_graph("SSH")
        self._put(name, self.grid.graphs.get(name, Graph()), replace=True)

    def _put(self, name: str, graph: Graph, *, replace: bool = False) -> None:
        """``graph`` into the named graph ``name``: one update per chunk, or, with ``replace``,
        one update that empties the graph first and moves the version stamp, so a reader never
        sees it empty, nor changed with the old stamp."""
        if isinstance(self.backend, LocalStore):
            with self.backend._lock:
                self.backend.put(name, graph, replace=replace)
                if replace:
                    self.backend.update(_BUMP)
            return
        if replace:
            self.backend.update(f"CLEAR SILENT GRAPH <{name}> ;\n{_insert(name, list(graph))} ;\n{_BUMP}")
            return
        # A fill goes through the graph store: a whole graph as N-Triples in one request, which the
        # server takes far faster than as many SPARQL updates.
        self.backend._post(graph, name)

    def wait_loaded(self, timeout: float = 120.0) -> None:
        """Return once the store holds a grid; ``TimeoutError`` after ``timeout`` seconds."""
        deadline, pause = time.monotonic() + timeout, 0.1
        while not (self.reachable() and self.loaded()):
            if time.monotonic() > deadline:
                raise TimeoutError(f"no grid in {self.backend.name} after {timeout:.0f} s: is the web backend loading it?")
            time.sleep(pause)
            pause = min(pause * 2, 2.0)


def _insert(graph: str, triples: list) -> str:
    body = "\n".join(f"{s.n3()} {p.n3()} {o.n3()} ." for s, p, o in triples)
    return f"INSERT DATA {{ GRAPH <{graph}> {{\n{body}\n}} }}"


_stores: dict[CimSettings, Store] = {}
_stores_lock = threading.Lock()


def open_store(settings: CimSettings | None = None) -> Store:
    """This process's handle on the store ``settings`` names. An in-process store is filled
    with the grid when it is first opened: nobody else could."""
    settings = settings or CimSettings.from_env()
    with _stores_lock:
        store = _stores.get(settings)
        if store is None:
            if settings.url is None:
                store = Store(settings, LocalStore())
                store.fill()
            else:
                store = Store(settings, _remote(settings.url))
            _stores[settings] = store
        return store


def connect_reader(
    settings: CimSettings | None = None, *, store: Store | None = None, timeout: float = 120.0
) -> ReadOnlyRepository:
    """A repository that reads the CIM graph (see the module), once the store holds one.
    ``store`` is the process's (``open_store``) unless given.

    One per reader and per thread: a repository is not thread-safe."""
    settings = settings or (store.settings if store is not None else CimSettings.from_env())
    store = store or open_store(settings)
    store.wait_loaded(timeout)
    policy = CachePolicy.cgmes_realtime(sv=None, ssh=None, tp=None)  # nothing on a timer: see GraphVersion
    return ReadOnlyRepository(
        store.backend,
        default_namespace=CIM100,
        graphs="discover",
        namespace_aliases=NAMESPACE_ALIASES,
        cache_policy=policy,
    )


def model_id(store: Store) -> str | None:
    """The id of the grid ``store`` holds (its EQ model's ``md:FullModel``), or ``None``:
    what a PMU frame's ``cimReferenceId`` says."""
    found = store.backend.execute(
        f"SELECT ?m WHERE {{ GRAPH <{model_graph('EQ')}> {{ ?m a <{_FULL_MODEL}> }} }} ORDER BY ?m LIMIT 1"
    )["results"]["bindings"]
    return found[0]["m"]["value"].removeprefix("urn:uuid:") if found else None


#: The profiles that change while the grid runs: what a reader reads again when the graph changed.
CHANGING = ("SSH", "SV")


def refresh_expired(repo: CIMRepository) -> None:
    """Mark what ``repo`` holds of the profiles that change (``CHANGING``) stale, so its next read
    reads them again; everything else it keeps. Nothing is queried here."""
    for profile in CHANGING:
        repo.expire(profile=profile)


class GraphVersion:
    """Whether the graph changed since the last look, from the version stamp: one tiny query.

    Made before reading what it guards, so a write in between is seen at the next look: the
    first ``changed()`` compares with the stamp as it was when the watch was made."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.seen = store.version()

    def changed(self) -> bool:
        now = self.store.version()
        moved, self.seen = now != self.seen, now
        return moved
