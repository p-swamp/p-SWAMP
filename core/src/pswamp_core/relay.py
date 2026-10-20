# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""A source that relays another pipeline's live run.

A pipeline's live source runs once, in its own pipeline's shared run (``live.<source>``).
Another pipeline takes what it needs from there instead of starting the feed again::

    [[sources]]
    name = "live-pmu"
    from = "pmu-pipeline"                     # pipelines/pmu-pipeline.toml
    get  = ["pmu", "frame-stats"]             # its live source, and modules running on it

Every name in ``get`` is a source or a module of that pipeline: exactly one live source
(its frames are this source's primary stream) and, besides, any modules whose results
are wanted. The relay is an ordinary live source of the pipeline that lists it: it
subscribes to those classes under the owner's ``live.<source>`` key and yields what
arrives, so the pipeline's run publishes it under its own key like any live feed, and
its modules read it like any other. The env form is ``name:@pipeline/get1+get2``.

One hop only: a relay of a relay is refused. The relay needs its run's transport
(``SourceModule.bind``), and the owner's pipeline must be started first (a subscriber
hears only what is published after it subscribes).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from pswamp_models.common import Command

from .pipeline import live_key
from .sources import SourceModule

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from datetime import datetime

    from pswamp_models.common import DataModel

    from .transport import Transport

__all__ = ["RelaySource", "relay_for"]


class RelaySource(SourceModule):
    """The base of a relay: see ``relay_for`` for the class a pipeline file gets."""

    name = "relay"
    kind = "live"
    abstract = True

    #: The pipeline relayed, and its live source.
    owner: ClassVar[str] = ""
    owner_source: ClassVar[str] = ""

    _transport: Transport | None = None

    def bind(self, transport: Transport) -> None:
        self._transport = transport

    async def aread(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterator[DataModel]:
        if self._transport is None:
            raise RuntimeError(f"relay of {self.owner}/{self.owner_source} was not bound to a transport")
        with self._transport.subscribe(*self.outputs, app=self.owner, key=live_key(self.owner_source)) as feed:
            async for _, message in feed:
                yield message


def relay_for(folder: Path | None, owner: str, get: Sequence[str]) -> type[RelaySource]:
    """The relay of ``get`` from pipeline ``owner``, whose file is ``<folder>/<owner>.toml``.

    Raises ``PipelineConfigError`` when the file is missing or bad, a name in ``get`` is
    neither a source nor a module of it, it names no live source or two, or that source
    is itself a relay.
    """
    from .pipeline_config import PipelineConfigError, load_pipeline

    def refuse(why: str) -> PipelineConfigError:
        return PipelineConfigError(f"from {owner!r}: {why}")

    if folder is None:
        raise refuse("this pipeline was not loaded from a file, so there is no folder to find it in")
    pipeline = load_pipeline(Path(folder) / f"{owner}.toml")
    sources = dict(pipeline.sources.source_classes())  # type: ignore[attr-defined]
    modules = {module.name: module for module in pipeline.modules}
    unknown = [name for name in get if name not in sources and name not in modules]
    if unknown:
        raise refuse(f"has no source or module {', '.join(unknown)}; it has {', '.join([*sources, *modules])}")
    live = [name for name in get if name in sources]
    if len(live) != 1:
        raise refuse(f"get must name exactly one live source, not {len(live)}; its sources are {', '.join(sources)}")
    source = sources[live[0]]
    if source.kind != "live":
        raise refuse(f"{live[0]!r} is a {source.kind}, and only a live source can be relayed")
    if issubclass(source, RelaySource):
        raise refuse(f"{live[0]!r} is itself a relay of {source.owner!r}; relay that one directly")
    outputs = list(source.outputs)
    for name in (name for name in get if name in modules):
        results = [model for model in modules[name].outputs if not issubclass(model, Command)]
        if not results:
            raise refuse(f"module {name!r} publishes no results to relay")
        outputs += results
    label = re.sub(r"\W", "_", f"Relay_{owner}_{live[0]}")
    return type(label, (RelaySource,), {"outputs": tuple(dict.fromkeys(outputs)), "owner": owner, "owner_source": live[0]})
