# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""The grid as it is loaded: every CGMES profile in a named graph of its own.

``stage`` reads the grid (the CGMES ``*_<PROFILE>.xml`` files of a folder, or
Nordic44, which LazyCIM downloads on first use: CC BY-NC-SA, never committed or
shipped) and the CGMES vocabularies, then completes it in a private, in-process
copy, before any store sees it:

- every synchronous machine without dynamics gets those of the nearest Nordic44
  machine (``add_nordic44_dynamics``), in ``cgmes:model:DY``;
- every place a PMU can observe gets its Analog (``analogs.add_pmu_analogs``), in
  ``cgmes:model:OP``, the Operation profile, which is where CGMES keeps
  measurements.

Data graphs are ``cgmes:model:<KW>`` and vocabularies ``cgmes:schema:<KW>``, the
convention LazyCIM reads (``graphs="discover"``). The result is what a store is
filled with and what a reset puts back.
"""

from __future__ import annotations

import functools
import threading
from dataclasses import dataclass
from pathlib import Path

from lazycim import CIMRepository, InMemoryGraphBackend
from lazycim.demo import CIM100, CorpusUnavailable, add_nordic44_dynamics, cgmes_profile_files, nordic44_files
from lazycim.export import vocabulary_source
from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from ..log import get_logger
from .analogs import add_pmu_analogs
from .settings import CimSettings

__all__ = ["NAMESPACE_ALIASES", "SAMPLE_GRID", "Grid", "model_graph", "schema_graph", "stage"]

logger = get_logger("pswamp_core.cim")

#: A small CGMES grid shipped with the core (Apache-2.0), for tests and for hosts with no
#: network: three substations, three lines, a bus coupler, a transformer, two generators, two loads.
SAMPLE_GRID = Path(__file__).parent / "sample_grid"

#: Nordic44's data says CIM100-EuropeanExtension where the CGMES vocabularies say CIM100-European.
NAMESPACE_ALIASES = {"http://iec.ch/TC57/CIM100-EuropeanExtension/1/0#": "http://iec.ch/TC57/CIM100-European#"}

_FULL_MODEL = URIRef("http://iec.ch/TC57/61970-552/ModelDescription/1#FullModel")


def model_graph(keyword: str) -> str:
    return f"cgmes:model:{keyword}"


def schema_graph(keyword: str) -> str:
    return f"cgmes:schema:{keyword}"


@dataclass(frozen=True)
class Grid:
    """The grid as loaded. Treat the graphs as read-only: a store copies them."""

    #: Graph name (``cgmes:model:EQ``, ``cgmes:schema:EQ``...) to its triples.
    graphs: dict[str, Graph]
    #: The EQ model's id (its ``md:FullModel``): what a PMU frame's ``cimReferenceId`` says.
    model_id: str
    #: Whether the vocabularies are in it: without them nothing can be created or edited.
    writable: bool

    def triples(self) -> int:
        return sum(len(graph) for graph in self.graphs.values())


_LOCK = threading.Lock()


def stage(settings: CimSettings | None = None) -> Grid:
    """The grid ``settings`` names, staged (see the module). Parsed once per process and folder.

    Raises ``RuntimeError`` saying what to do when the grid cannot be had."""
    settings = settings or CimSettings.from_env()
    with _LOCK:
        return _stage(settings.cim_path)


@functools.cache
def _stage(folder: Path | None) -> Grid:
    if folder is None:
        try:
            files = nordic44_files()
        except CorpusUnavailable as error:
            raise RuntimeError(
                f"{error}. Nordic44 is downloaded on first use: set PSWAMP_CIM_PATH to a folder of CGMES "
                "files, or fill LazyCIM's cache while online (python -m lazycim.demo)."
            ) from error
    else:
        files = sorted(folder.glob("*.xml")) if folder.is_dir() else []
        if not files:
            raise RuntimeError(f"{folder} is not a folder of CGMES *_<PROFILE>.xml files")

    graphs: dict[str, Graph] = {}
    for file in files:
        keyword = file.stem.rsplit("_", 1)[-1].upper()
        # LazyCIM's loader parses under one base URI, so the profiles' fragments name the same objects.
        graphs.setdefault(model_graph(keyword), Graph()).__iadd__(InMemoryGraphBackend(file.name).load(file, format="xml").graph)
    model_id = _model_id(graphs.get(model_graph("EQ")), folder)

    try:
        vocabularies = cgmes_profile_files(dynamics=True)
    except CorpusUnavailable as error:
        logger.warning("the CGMES vocabularies are not available (%s): the graph is read-only, with no PMU Analogs", error)
        return Grid(graphs, model_id, writable=False)
    for file in vocabularies:
        graphs[schema_graph(str(vocabulary_source(file).keyword))] = Graph().parse(file, format="xml")

    merged = InMemoryGraphBackend("stage")
    for graph in graphs.values():
        merged.graph.__iadd__(graph)
    repo = CIMRepository(merged, default_namespace=CIM100, namespace_aliases=NAMESPACE_ALIASES)
    _complete(merged.graph, graphs, model_graph("DY"), lambda: add_nordic44_dynamics(repo), "machines given dynamics")
    _complete(merged.graph, graphs, model_graph("OP"), lambda: _analogs(repo), "PMU Analogs")
    return Grid(graphs, model_id, writable=True)


def _analogs(repo: CIMRepository) -> int:
    added = add_pmu_analogs(repo)
    repo.commit()
    return added


def _complete(merged: Graph, graphs: dict[str, Graph], name: str, step, what: str) -> None:
    """Run ``step`` (it creates objects and commits) and file what it created under ``name``."""
    before = set(merged)
    count = step()
    created = graphs.setdefault(name, Graph())
    for triple in set(merged) - before:
        created.add(triple)
    logger.info("%d %s", count, what)


def _model_id(eq: Graph | None, folder: Path | None) -> str:
    subject = next(iter(sorted(eq.subjects(RDF.type, _FULL_MODEL))), None) if eq is not None else None
    if subject is None:
        return folder.name if folder is not None else "nordic44"
    text = str(subject)
    return text.removeprefix("urn:uuid:")
