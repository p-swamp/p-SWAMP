# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``SourceModule``: where a pipeline's data comes from, written as a module.

A source is a module like any other: a ``Module`` subclass, in a project of
its own (``modules/<name>/``, an entry point in ``pswamp.modules``). It has no
inputs: it *produces* messages, ``PmuFrame`` by default. Where it differs is
where it runs: in the process that owns its run, read by the run's
``ActiveSource`` router, never in a ``ModuleHost`` on the transport (ADR-005,
ADR-006). For a source, ``blocking`` governs ``read``, ``coverage``, ``open``
and ``close``. It is of one of two ``kind``s:

- ``history``: holds a range of records (a recording, a store).
  ``coverage()`` says which; ``read(start, end)`` yields the records in a
  range and stops. A history that also mixes in ``Playable``
  (``pswamp_core.playable``) can be replayed in real time and sought.
- ``live``: a feed. ``coverage()`` is ``None``; ``read`` yields records as they
  arrive, from now, until ``end`` or for ever.

**The author writes one of two methods**; the base class derives the other::

    class SampleReplay(Playable, SourceModule):
        name = "sample-replay"
        kind = "history"

        def read(self, start=None, end=None):            # plain synchronous code
            for frame in self.frames:
                if in_range(frame, start, end):
                    yield frame

        def coverage(self):
            return TimeRange(...)

    class RemoteHistory(Playable, SourceModule):
        async def aread(self, start=None, end=None):     # or async, when the data is
            async for record in self._query(start, end):
                yield record

*From a script* call the synchronous form, no event loop in sight::

    for frame in SampleReplay().read():
        stats.run_one(frame)

*The host* (the server, a worker) calls ``aread``. Implemented as ``read``, it
runs inline, or in a thread per record when ``blocking = True`` (the right
setting for a source that waits on a file or a socket). Implemented as
``aread``, ``read`` drives it on a private event loop, and raises a clear
``RuntimeError`` when called from inside a running one: use ``aread`` there.
``coverage`` / ``acoverage`` and ``open`` / ``aopen`` / ``close`` / ``aclose``
pair the same way. ``open`` and ``close`` are optional (a connection, a ticker),
and a source is a context manager: ``with source:`` or ``async with source:``.
A source that needs a resource across several reads should open it in
``aopen`` only if every read happens in the host's loop; otherwise make it
per call, as ``RemoteHistory`` does.

**The contract**, checked by ``pswamp_core.testing.SourceConformance``:
``read`` yields only declared ``outputs`` (``outputs[0]`` is the primary
stream), each with a UTC ``timestamp`` and in timestamp order, in the
half-open range ``[start, end)``; closing the iterator early releases what it
holds. A history's ``coverage`` spans its records.

**Settings** are the core's ``Configurable`` settings: the class lists
``env_settings``; a deployment sets ``{SOURCE}_{SETTING}`` (``SOURCE`` is the
instance name, ``sample`` in ``SAMPLE_PATH``) and ``from_env(name)`` reads
them; a script passes them as keywords, ``SampleReplay(path="mine.txt")``.
They arrive as ``self.settings``.

A class is checked when it is defined (``__init_subclass__``): ``name`` set,
``kind`` known, ``read`` or ``aread`` implemented, a history's ``coverage``
implemented, ``outputs`` made of ``DataModel`` classes. A class that is only a
base for others sets ``abstract = True`` in its own body to skip the check.

``SourceSet`` is a run's sources: named instances, one of them active.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, Literal

from pswamp_models.common import Command, DataModel
from pswamp_models.pmu import PmuFrame

from .enrich import Enricher
from .log import get_logger
from .modules import Module
from .settings import Configurable, EnvSetting, MissingSettingError, parse_setting, read_setting
from .time_range import TimeRange

__all__ = ["SourceModule", "SourceSet", "SourceStream"]

logger = get_logger("pswamp_core.sources")

_END = object()
_KINDS = ("live", "history")


def _defines(cls: type, method: str) -> bool:
    """Whether ``cls`` implements ``method`` itself, not just through the base."""
    return getattr(cls, method) is not getattr(SourceModule, method)


def _no_running_loop(what: str, use: str) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        f"{what} is implemented as async code and cannot be called from inside a running event loop; "
        f"use `await ...{use}` there"
    )


def _drive(records: AsyncIterator[DataModel]) -> Iterator[DataModel]:
    """An async iterator as a plain one, on a private event loop."""
    loop = asyncio.new_event_loop()
    try:
        while True:
            try:
                yield loop.run_until_complete(records.__anext__())
            except StopAsyncIteration:
                return
    finally:
        with contextlib.suppress(Exception):
            loop.run_until_complete(records.aclose())  # type: ignore[attr-defined]
            loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


def _coerce(setting: EnvSetting, value: Any) -> Any:
    """A script's keyword in the type the setting's ``kind`` promises."""
    if value is None:
        return None
    if setting.kind == "path" and isinstance(value, str):
        return Path(value)
    if setting.kind == "seconds" and isinstance(value, int | float):
        return timedelta(seconds=value)
    if setting.kind == "list" and isinstance(value, str):
        return parse_setting(setting.setting, setting, value)
    return value


class SourceModule(Module, Configurable):
    """One data source. Subclass it; see the module docstring for the contract.

    Class attributes:
        name: The module's name: its entry point's, and the default instance name.
        kind: ``"history"`` (a seekable range) or ``"live"`` (a feed).
        outputs: The classes it produces; ``outputs[0]`` is the primary,
            paced stream. ``model`` is that class.
        blocking: ``read`` / ``coverage`` / ``open`` / ``close`` wait on
            something: the host runs them in a thread, off the event loop.
        env_settings: The ``{SOURCE}_{SETTING}`` variables it reads.
        commands: The commands it answers; ``()`` unless a mixin
            (``Playable``) adds some.
        abstract: Set in a class's own body: it is a base for sources, not one.

    Args:
        source: This instance's name in a run (``sample``, ``live``); the
            module's ``name`` if omitted.
        **settings: Values for ``env_settings``, by lower-cased keyword.
    """

    name: ClassVar[str] = ""
    kind: ClassVar[Literal["live", "history"]]
    outputs: ClassVar[tuple[type[DataModel], ...]] = (PmuFrame,)
    blocking: ClassVar[bool] = False
    commands: ClassVar[tuple[type[Command], ...]] = ()
    abstract: ClassVar[bool] = False
    #: The primary output class; set per class from ``outputs``.
    model: ClassVar[type[DataModel]] = PmuFrame

    _is_open: bool = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("abstract", False):
            return
        label = cls.__name__
        if not isinstance(cls.name, str) or not cls.name:
            raise TypeError(f"{label} must set `name` (its entry-point name)")
        if getattr(cls, "kind", None) not in _KINDS:
            raise TypeError(f"{label}.kind must be one of {_KINDS}, not {getattr(cls, 'kind', None)!r}")
        if not (_defines(cls, "read") or _defines(cls, "aread")):
            raise TypeError(f"{label} must implement `read` or `aread`")
        if cls.kind == "history" and not (_defines(cls, "coverage") or _defines(cls, "acoverage")):
            raise TypeError(f"{label} is a history: it must implement `coverage` or `acoverage`")
        outputs = cls.outputs
        if not (
            isinstance(outputs, tuple)
            and outputs
            and all(isinstance(o, type) and issubclass(o, DataModel) for o in outputs)
        ):
            raise TypeError(f"{label}.outputs must be a non-empty tuple of DataModel classes, not {outputs!r}")
        for setting in cls.env_settings:
            if not isinstance(setting, EnvSetting):
                raise TypeError(f"{label}.env_settings must hold EnvSetting entries, not {setting!r}")
        cls.model = outputs[0]

    def __init__(self, source: str | None = None, **settings: Any) -> None:
        super().__init__()
        self.source: str = source or self.name
        declared = {setting.setting.lower(): setting for setting in self.env_settings}
        unknown = sorted(set(settings) - set(declared))
        if unknown:
            raise TypeError(f"{type(self).__name__} has no setting {', '.join(unknown)}; it declares {sorted(declared)}")
        values: dict[str, Any] = {}
        for keyword, setting in declared.items():
            if keyword in settings:
                values[keyword] = _coerce(setting, settings[keyword])
            elif setting.default is not None:
                values[keyword] = parse_setting(keyword, setting, setting.default)
            elif setting.required:
                raise MissingSettingError(f"{type(self).__name__} needs the setting {keyword!r}")
            else:
                values[keyword] = None
        #: The settings in force, by lower-cased keyword: ``self.settings.path``.
        self.settings = SimpleNamespace(**values)
        self.parameters = dict(values)

    @classmethod
    def from_env(cls, name: str, **overrides: Any):
        """An instance called ``name``, its settings read from ``{NAME}_{SETTING}``
        unless ``overrides`` supplies them."""
        settings: dict[str, Any] = {}
        for setting in cls.env_settings:
            keyword = setting.setting.lower()
            if keyword not in overrides:
                value = read_setting(name, setting)
                if value is not None:
                    settings[keyword] = value
        return cls(name, **settings, **overrides)

    # -- reading -------------------------------------------------------------------

    def read(self, start: datetime | None = None, end: datetime | None = None) -> Iterator[DataModel]:
        """The records in ``[start, end)`` (``None``: unbounded), in order.

        The synchronous form, for scripts. A source written as ``aread`` is
        driven on a private event loop; that cannot be done from inside a
        running one, and raises ``RuntimeError``."""
        _no_running_loop(f"{type(self).__name__}.read", "aread(...)")
        return _drive(self.aread(start, end))

    async def aread(self, start: datetime | None = None, end: datetime | None = None) -> AsyncIterator[DataModel]:
        """The same records, for the host. A source written as ``read`` runs
        inline, or in a thread per record when ``blocking``."""
        iterator = iter(self.read(start, end))
        try:
            while True:
                record = await asyncio.to_thread(next, iterator, _END) if self.blocking else next(iterator, _END)
                if record is _END:
                    return
                yield record
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                with contextlib.suppress(ValueError):  # a thread may still be inside it
                    close()

    def coverage(self) -> TimeRange | None:
        """The range a history holds, ``[first, end)``; ``None`` for a live
        feed or a history holding nothing."""
        if _defines(type(self), "acoverage"):
            _no_running_loop(f"{type(self).__name__}.coverage", "acoverage()")
            return asyncio.run(self.acoverage())
        return None

    async def acoverage(self) -> TimeRange | None:
        if _defines(type(self), "coverage"):
            return await asyncio.to_thread(self.coverage) if self.blocking else self.coverage()
        return None

    # -- resources -----------------------------------------------------------------

    def open(self) -> None:
        """Acquire resources (optional). Called once, before the first read."""
        if _defines(type(self), "aopen"):
            _no_running_loop(f"{type(self).__name__}.open", "aopen()")
            asyncio.run(self.aopen())

    async def aopen(self) -> None:
        if _defines(type(self), "open"):
            if self.blocking:
                await asyncio.to_thread(self.open)
            else:
                self.open()

    def close(self) -> None:
        """Release them (optional)."""
        if _defines(type(self), "aclose"):
            _no_running_loop(f"{type(self).__name__}.close", "aclose()")
            asyncio.run(self.aclose())

    async def aclose(self) -> None:
        if _defines(type(self), "close"):
            if self.blocking:
                await asyncio.to_thread(self.close)
            else:
                self.close()

    async def _ensure_open(self) -> None:
        """Open once, however many callers ask (the host's ``SourceSet``, a ``Playable``)."""
        if not self._is_open:
            await self.aopen()
            self._is_open = True

    async def _ensure_closed(self) -> None:
        if self._is_open:
            self._is_open = False
            await self.aclose()

    def __enter__(self):
        self.open()
        self._is_open = True
        return self

    def __exit__(self, *exc: object) -> None:
        self._is_open = False
        self.close()

    async def __aenter__(self):
        await self._ensure_open()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._ensure_closed()


# --- what a run reads through ---------------------------------------------------------


class SourceStream:
    """One forward-only pass over one source's range, made safe for everyone
    downstream: a record without a timestamp is dropped, nothing at or past the
    range's end is yielded, every record passes through the enrichers, and
    closing the stream closes the source's iterator. A seek is a new stream.
    """

    def __init__(self, source: SourceModule, time_range: TimeRange, enrichers: Sequence[Enricher] = ()) -> None:
        self.source = source
        self.time_range = time_range
        self.enrichers = tuple(enrichers)
        self._iterator: AsyncIterator[DataModel] | None = None

    def __aiter__(self) -> SourceStream:
        return self

    async def __anext__(self) -> DataModel:
        if self._iterator is None:
            self._iterator = self._iterate()
        return await self._iterator.__anext__()

    async def aclose(self) -> None:
        """Stop, and release the source's iterator."""
        iterator, self._iterator = self._iterator, None
        if iterator is not None:
            await iterator.aclose()  # type: ignore[attr-defined]

    async def _iterate(self) -> AsyncIterator[DataModel]:
        records = self.source.aread(self.time_range.start, self.time_range.end)
        end = self.time_range.end
        try:
            async for record in records:
                if record.timestamp is None:
                    logger.warning("dropping a record without a timestamp from %s", self.source.source)
                    continue
                if end is not None and record.timestamp >= end:
                    return
                for enricher in self.enrichers:
                    record = enricher.enrich(record)
                yield record
        finally:
            closer = getattr(records, "aclose", None)
            if closer is not None:
                await closer()


class SourceSet:
    """A run's sources as named instances, one of them active.

        sources.sources                     # ["sample", "live"], in declared order
        sources.source, sources.live        # the active one, and whether it is a live feed
        sources.switch("live")              # another is active from now on
        sources.consume(start=t0)           # from t0 onwards: a seek
        sources.consume(start=t0, end=t1)   # exactly [t0, t1): a chunk

    One at a time, and only an explicit switch changes it, so a stream always
    has exactly one source behind it. A source is opened on first use, so one
    nobody reads costs nothing. A run holds one (``PipelineRun.sources``), and
    a module that ``reads_sources`` is given one (``Module.sources``).

    Args:
        sources: The instances, in order; the first is active unless ``active``
            names another. Their ``source`` names are what a run switches by.
        enrichers: Applied, in order, to every record a stream yields.

    Raises:
        ValueError: None, two with one name, or ``active`` names none.
    """

    def __init__(
        self, sources: Sequence[SourceModule], *, active: str | None = None, enrichers: Sequence[Enricher] = ()
    ) -> None:
        if not sources:
            raise ValueError("a source set needs at least one source")
        self.instances: dict[str, SourceModule] = {}
        for instance in sources:
            if instance.source in self.instances:
                raise ValueError(f"two sources are named {instance.source!r}")
            self.instances[instance.source] = instance
        self._active = self._named(active) if active is not None else sources[0]
        self.enrichers = tuple(enrichers)

    @property
    def sources(self) -> list[str]:
        """The sources' names, in declared order."""
        return list(self.instances)

    @property
    def active(self) -> SourceModule:
        return self._active

    @property
    def source(self) -> str:
        """The active source's name."""
        return self._active.source

    @property
    def live(self) -> bool:
        """Whether the active source is a live feed."""
        return self._active.kind == "live"

    def kind(self, source: str) -> str:
        """``"history"`` or ``"live"``."""
        return self._named(source).kind

    def switch(self, source: str) -> SourceModule:
        """Make ``source`` the active one. An open stream is the caller's to close."""
        self._active = self._named(source)
        logger.info("source set switched to %s", source)
        return self._active

    async def coverage(self) -> TimeRange | None:
        """What the active source holds; ``None`` for a live feed. Raises what
        the source raises."""
        await self._active._ensure_open()
        return await self._active.acoverage()

    async def consume(self, start: datetime | None = None, end: datetime | None = None) -> SourceStream:
        """A stream over ``[start, end)`` of the active source."""
        await self._active._ensure_open()
        return SourceStream(self._active, TimeRange(start, end), self.enrichers)

    async def close(self) -> None:
        """Close every source that was opened."""
        for instance in self.instances.values():
            try:
                await instance._ensure_closed()
            except Exception as error:
                logger.error("source %s failed to close: %s", instance.source, error)

    def _named(self, source: str) -> SourceModule:
        instance = self.instances.get(source)
        if instance is None:
            raise ValueError(f"no source named {source!r}; the sources are {list(self.instances)}")
        return instance
