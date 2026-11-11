"""A history source with ``inputs`` and a ``FEED`` is fed the frames of that live source's shared run, and only by it."""

from __future__ import annotations

import asyncio

from support import TickingSource
from test_pipeline import until

from pswamp_core.pipeline import Pipeline, PipelineRun, start_live_runs
from pswamp_core.settings import EnvSetting
from pswamp_core.sources import SourceModule, SourceSet
from pswamp_core.transport import InMemoryTransport
from pswamp_models.pmu import PmuFrame


class Tape(SourceModule):
    """Keeps what it is fed; a history that holds nothing to replay."""

    name = "tape"
    kind = "history"
    inputs = (PmuFrame,)
    env_settings = (EnvSetting("FEED", "The live source it records"),)

    def __init__(self, source: str = "tape", **settings) -> None:
        super().__init__(source, **settings)
        self.got: list[PmuFrame] = []
        self.torn_down = False

    def process(self, frame: PmuFrame) -> None:
        self.got.append(frame)

    async def teardown(self) -> None:
        self.torn_down = True

    def coverage(self):
        return None

    def read(self, start=None, end=None):
        return iter(())


def pipeline(feed: str | None = "tick") -> Pipeline:
    return Pipeline("app", lambda: SourceSet([TickingSource("tick"), Tape(feed=feed)]))


async def test_the_shared_live_run_feeds_the_tape_and_a_client_run_does_not():
    transport = InMemoryTransport()
    app = pipeline()
    (live,) = await start_live_runs(app, transport)
    client = PipelineRun("a", app, transport)
    await client.start()
    tape = live.sources.instances["tape"]
    await until(lambda: len(tape.got) >= 3, timeout=2)
    assert [f.timestamp for f in tape.got] == sorted(f.timestamp for f in tape.got)
    assert client.sources.instances["tape"].got == []
    await client.stop()
    await live.stop()


async def test_stopping_the_run_tears_the_tape_down():
    transport = InMemoryTransport()
    (live,) = await start_live_runs(pipeline(), transport)
    tape = live.sources.instances["tape"]
    await until(lambda: len(tape.got) >= 1, timeout=2)
    await live.stop()
    assert tape.torn_down


async def test_a_tape_whose_feed_is_another_source_is_not_fed():
    transport = InMemoryTransport()
    (live,) = await start_live_runs(pipeline(feed="elsewhere"), transport)
    await asyncio.sleep(0.2)
    assert live.sources.instances["tape"].got == []
    await live.stop()
