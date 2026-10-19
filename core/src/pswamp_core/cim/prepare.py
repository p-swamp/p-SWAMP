# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Readying a script's own LazyCIM repository for p-SWAMP, as the core readies a grid it loads.

A grid the core loads (``grid.stage``) gets dynamics for every machine without any, and a PMU Analog
wherever a PMU can observe, which is what a frame's columns point at. A repository a script made
itself, over any LazyCIM backend (a demo model in an embedded Oxigraph, a GraphDB repository), may
have neither; ``prepare`` adds what is missing, once. It writes to that repository's store only:
never call it on the deployment's store, whose one writer is the web backend.
"""

from __future__ import annotations

from lazycim import CIMRepository, GraphLayout
from lazycim.demo import CIM100, add_nordic44_dynamics

from .analogs import add_pmu_analogs, analog_table
from .grid import NAMESPACE_ALIASES, model_graph, schema_graph
from .store import PROFILES

__all__ = ["prepare"]


def prepare(repo: CIMRepository, *, dynamics: bool = True) -> int:
    """Give the grid in ``repo``'s store its PMU Analogs, and (``dynamics``) its machines without
    dynamics Nordic44's, unless it has them; how many Analogs were added.

    It writes through a repository of its own, laid out with a graph per profile as the core's
    writer is (a profile's graph is created on its first write: the Dynamics and Operation ones are
    often missing), so ``repo`` itself reads the result afresh. Needs the store to hold the CGMES
    vocabularies, Dynamics and Operation included (LazyCIM's demo loaders put them there)."""
    writer = _writer(repo)
    if dynamics:
        add_nordic44_dynamics(writer)  # leaves a machine that has dynamics alone; commits
    if len(analog_table(writer)):
        return 0
    added = add_pmu_analogs(writer)
    writer.commit()
    return added


def _writer(repo: CIMRepository) -> CIMRepository:
    """A repository over ``repo``'s store that writes as the core's writer does: every profile's data
    graph, and the vocabularies the store holds."""
    found = repo.db.execute("SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }")["results"]["bindings"]
    names = [row["g"]["value"] for row in found]
    prefix = schema_graph("")
    schema = {name.removeprefix(prefix): name for name in names if name.startswith(prefix)}
    layout = GraphLayout(model={keyword: model_graph(keyword) for keyword in PROFILES}, schema=schema)
    return CIMRepository(repo.db, default_namespace=CIM100, graphs=layout, namespace_aliases=NAMESPACE_ALIASES)
