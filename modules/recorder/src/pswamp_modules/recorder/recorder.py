"""``Recorder``: records the messages it is told to keep, and plays the frames back as a history source."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

from pswamp_core.playable import Playable
from pswamp_core.settings import EnvSetting, MissingSettingError
from pswamp_core.sources import SourceModule
from pswamp_core.time_range import TimeRange
from pswamp_models.common import DataModel, recordable_models
from pswamp_models.pmu import PmuFrame

from .store import Store
from .tables import codec_for

__all__ = ["Recorder"]


class Recorder(Playable, SourceModule):
    """Fed the messages ``MESSAGES`` names (``process``), it keeps them under ``DIR``; as a source it reads the frames back."""

    name = "recorder"
    kind = "history"
    blocking = True
    inputs = (PmuFrame,)
    outputs = (PmuFrame,)
    env_settings = (
        EnvSetting("DIR", "The folder the recordings are kept in", required=True, kind="path"),
        EnvSetting("FEED", "The live source it records; none: it only plays back what it holds"),
        EnvSetting(
            "MESSAGES",
            "The messages it keeps, comma separated, by topic or class name (any recordable message of pswamp_models)",
            default="PmuFrame",
            kind="list",
        ),
        EnvSetting("ROLL_HOURS", "Hours of frames after which a new segment starts", default="6", kind="float"),
        EnvSetting("FLUSH_SECONDS", "Seconds between writes to disk", default="1", kind="seconds"),
        EnvSetting("MAX_BYTES", "Bytes kept: the oldest segments go first", default=str(5 * 1024**3), kind="int"),
    )

    def __init__(self, source: str | None = None, **settings: Any) -> None:
        super().__init__(source, **settings)
        #: What this instance keeps: ``inputs`` of the class says only what it does by default.
        self.recorded: tuple[type[DataModel], ...] = self._select(self.settings.messages)
        self.inputs = self.recorded
        self._handlers = {model: "process" for model in self.recorded}
        self.store = Store(
            self.settings.dir / self.source,
            roll=timedelta(hours=self.settings.roll_hours),
            flush_every=self.settings.flush_seconds,
            max_bytes=self.settings.max_bytes,
            codecs=[codec_for(model) for model in self.recorded],
        )

    @staticmethod
    def _select(names: list[str]) -> tuple[type[DataModel], ...]:
        """The recordable classes ``names`` stand for (a topic or a class name each); an unknown one is an error."""
        available = recordable_models()
        by_name = {model.__name__: model for model in available.values()}
        chosen: dict[type[DataModel], None] = {}
        for name in names:
            model = available.get(name) or by_name.get(name)
            if model is None:
                raise MissingSettingError(
                    f"recorder MESSAGES: {name!r} is not a recordable message; choose from {', '.join(available)}"
                )
            chosen[model] = None
        if not chosen:
            raise MissingSettingError("recorder MESSAGES names nothing")
        return tuple(chosen)

    def input_models(self) -> tuple[type[DataModel], ...]:  # type: ignore[override]
        return self.recorded

    def queued_inputs(self) -> tuple[type[DataModel], ...]:  # type: ignore[override]
        return self.recorded

    def process(self, message: DataModel) -> None:
        self.store.append(message)

    def reset(self) -> None:
        """The run's stream starts over: what comes next is a segment of its own."""
        self.store.roll_over()

    async def teardown(self) -> None:
        await asyncio.to_thread(self.store.flush)

    def flush(self) -> None:
        self.store.flush()

    @property
    def idle_flush_seconds(self) -> float:
        """How long a quiet feed may leave frames buffered: the run flushes the recorder after this much silence."""
        return max(self.store.flush_every.total_seconds(), 0.05)

    def read(self, start: datetime | None = None, end: datetime | None = None) -> Iterator[PmuFrame]:
        return self.store.read(start, end)

    def coverage(self) -> TimeRange | None:
        self.store.flush()
        bounds = self.store.bounds()
        return None if bounds is None else TimeRange(bounds[0], bounds[1] + timedelta(microseconds=1))
