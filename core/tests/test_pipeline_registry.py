"""The registry's bounds, with a stand-in run: one per key, a cap that holds
under a burst, idle and capacity eviction, and no leaked locks."""

from __future__ import annotations

import asyncio

import pytest

from pswamp_core.pipeline import CapacityError, PipelineRegistry


class FakeRun:
    def __init__(self, key: str) -> None:
        self.key = key
        self.stopped = False
        self.following = None

    async def start(self) -> None:
        await asyncio.sleep(0)  # yield, as a real start does

    async def stop(self, reason: str = "stopped") -> None:
        self.stopped = True


@pytest.fixture
async def registry():
    made = []

    def make(*, max_runs: int = 3, idle_seconds: float = 0.02, factory=FakeRun):
        made.append(PipelineRegistry(factory, max_runs=max_runs, idle_seconds=idle_seconds))
        return made[-1]

    yield make
    for reg in made:
        await reg.stop_all()


async def until(condition, timeout: float = 1.0) -> None:
    async def poll():
        while not condition():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


async def test_one_key_many_sockets_one_run(registry):
    reg = registry()
    runs = await asyncio.gather(*(reg.acquire("c1") for _ in range(5)))
    assert reg.live == 1 and len({id(r) for r in runs}) == 1 and reg.watchers("c1") == 5


async def test_a_burst_of_distinct_keys_never_exceeds_the_cap(registry):
    reg = registry(max_runs=3)
    results = await asyncio.gather(*(reg.acquire(f"c{i}") for i in range(7)), return_exceptions=True)
    assert sum(not isinstance(r, Exception) for r in results) == 3
    assert sum(isinstance(r, CapacityError) for r in results) == 4
    assert reg.live == 3 and reg._pending == 0


async def test_at_the_cap_an_idle_run_is_evicted_and_a_watched_one_is_not(registry):
    reg = registry(max_runs=2, idle_seconds=5.0)
    first = await reg.acquire("c0")
    reg.release("c0")
    await reg.acquire("c1")
    await reg.acquire("c2")
    assert first.stopped and reg.keys() == ["c1", "c2"] and "c0" not in reg._locks
    with pytest.raises(CapacityError):
        await reg.acquire("c3")
    assert reg.peek("c3") is None


async def test_an_idle_run_is_evicted_and_its_lock_reclaimed(registry):
    reg = registry(idle_seconds=0.02)
    for i in range(3):
        await reg.acquire(f"c{i}")
        reg.release(f"c{i}")
    await until(lambda: reg.live == 0)
    assert reg._locks == {} and reg._acquiring == {}


async def test_a_reconnect_before_the_idle_timeout_keeps_the_run(registry):
    reg = registry(idle_seconds=0.05)
    first = await reg.acquire("c1")
    reg.release("c1")
    assert await reg.acquire("c1") is first
    await asyncio.sleep(0.1)
    assert reg.live == 1


async def test_a_failed_start_leaves_nothing_behind(registry):
    class Boom(FakeRun):
        async def start(self):
            raise RuntimeError("boom")

    reg = registry(factory=Boom)
    with pytest.raises(RuntimeError, match="boom"):
        await reg.acquire("c1")
    assert (reg.live, reg._pending, reg._locks, reg._acquiring) == (0, 0, {}, {})


async def test_a_session_holds_the_run_for_one_connection(registry):
    reg = registry()
    async with reg.session("c9") as run:
        assert run.key == "c9" and reg.watchers("c9") == 1
    assert reg.watchers("c9") == 0


async def test_what_a_key_publishes_is_watched_by_its_run_or_the_runs_following_it(registry):
    reg = registry()
    a, b, _ = [await reg.acquire(key) for key in ("a", "b", "c")]
    a.following = b.following = "live.feed"
    assert reg.watching("c") == ["c"]
    assert sorted(reg.watching("live.feed")) == ["a", "b"]
    assert reg.watching("gone") == []
