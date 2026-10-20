"""A source that relays another pipeline's live run (``pswamp_core.relay``).

Pipeline files are written to ``tmp_path`` and the modules faked as installed,
as in test_pipeline_config.py."""

from __future__ import annotations

import asyncio

import pytest
from support import NumberResult, install_modules, write_pipeline

from pswamp_core.host import serve_hosts
from pswamp_core.modules import Module
from pswamp_core.pipeline import Pipeline, PipelineRun, start_live_runs
from pswamp_core.pipeline_config import PipelineConfigError
from pswamp_core.relay import RelaySource
from pswamp_core.transport import InMemoryTransport
from pswamp_core.util.tasks import cancel_and_wait
from pswamp_models.pmu import PmuFrame

A = """
app = "a"
modules = ["counter"]

[[sources]]
name = "tick"
module = "ticking-source"
"""

B = """
app = "b"

[[sources]]
name = "feed"
from = "a"
get = ["tick", "counter"]
"""


class ReadsNumber(Module):
    """Reads a result that only the relay brings."""

    name = "reads-number"
    inputs = (NumberResult,)

    def process(self, message: NumberResult) -> None:
        return None


class Silent(Module):
    """Publishes no result."""

    name = "silent"
    inputs = (PmuFrame,)

    def process(self, frame: PmuFrame) -> None:
        return None


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    install_modules(
        monkeypatch,
        counter="test_pipeline:FrameCounter",
        silent="test_relay:Silent",
        **{
            "ticking-source": "support:TickingSource",
            "list-source": "support:ListSource",
            "reads-number": "test_relay:ReadsNumber",
        },
    )
    monkeypatch.delenv("B_SOURCES", raising=False)


def load(tmp_path, name: str, text: str) -> Pipeline:
    return Pipeline.load(write_pipeline(tmp_path / f"{name}.toml", text))


async def until(condition, timeout: float = 5.0) -> None:
    async def poll():
        while not condition():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


async def test_a_pipeline_relays_the_frames_and_the_module_results_of_anothers_live_run(tmp_path):
    a = load(tmp_path, "a", A)
    b = load(tmp_path, "b", B.replace("[[sources]]", 'modules = ["reads-number"]\n\n[[sources]]'))
    assert b.source_models == (PmuFrame, NumberResult)  # so a module of b may read the result
    transport = InMemoryTransport()
    hosting = asyncio.create_task(serve_hosts(a.hosts(transport)))
    await asyncio.sleep(0)
    (owner,) = await start_live_runs(a, transport)
    (relayed,) = await start_live_runs(b, transport)
    try:
        assert isinstance(relayed.sources.instances["feed"], RelaySource) and relayed.key == "live.feed"
        await until(lambda: relayed.frame is not None and relayed.latest.get(NumberResult) is not None)
        assert type(relayed.frame) is PmuFrame  # a result is not the frame at the cursor
        assert relayed.router.last_frame is relayed.frame
        # The feed itself runs once, in the owner's run.
        assert owner.sources.instances["tick"].opened == 1
    finally:
        await relayed.stop()
        await owner.stop()
        await cancel_and_wait(hosting)


async def test_the_environment_can_replace_the_relayed_names(tmp_path, monkeypatch):
    load(tmp_path, "a", A)
    b = load(tmp_path, "b", B)
    monkeypatch.setenv("B_SOURCES", "frames:@a/tick")
    sources = b.sources()
    assert sources.sources == ["frames"] and b.sources.source_models() == (PmuFrame,)
    assert isinstance(sources.active, RelaySource)
    assert (sources.active.owner, sources.active.owner_source) == ("a", "tick")


async def test_a_relay_that_was_not_bound_to_a_transport_says_so(tmp_path):
    load(tmp_path, "a", A)
    (relay,) = load(tmp_path, "b", B).sources().instances.values()
    with pytest.raises(RuntimeError, match="was not bound to a transport"):
        await anext(relay.aread())


def test_a_run_binds_its_sources_to_its_transport(tmp_path):
    load(tmp_path, "a", A)
    b = load(tmp_path, "b", B)
    transport = InMemoryTransport()
    (relay,) = PipelineRun("k", b, transport).sources.instances.values()
    assert relay._transport is transport


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        (B.replace('from = "a"\n', 'from = "a"\nmodule = "ticking-source"\n'), "`module` (a source module) or `from`"),
        (B.replace('from = "a"\n', ""), "`module` (a source module) or `from`"),
        (B.replace('get = ["tick", "counter"]', ""), "`get` goes with `from`, and `from` needs it"),
        (B.replace('from = "a"', 'module = "ticking-source"'), "`get` goes with `from`"),
        (B.replace('from = "a"', 'from = "Nowhere"'), "sources.0.from"),
        (B.replace('"a"', '"nowhere"'), "no such pipeline file"),
        (B.replace('"tick", "counter"', '"tick", "nope"'), "from 'a': has no source or module nope; it has tick, counter"),
        (B.replace('"tick", "counter"', '"counter"'), "get must name exactly one live source, not 0"),
    ],
)
def test_a_bad_relay_says_which_and_why(tmp_path, text, complaint):
    load(tmp_path, "a", A)
    with pytest.raises(PipelineConfigError, match="b.toml") as raised:
        load(tmp_path, "b", text)
    assert complaint in str(raised.value)


def test_only_one_live_source_of_the_owner_may_be_named(tmp_path):
    load(tmp_path, "a", A + '\n[[sources]]\nname = "tock"\nmodule = "ticking-source"\n')
    with pytest.raises(PipelineConfigError, match="exactly one live source, not 2"):
        load(tmp_path, "b", B.replace('"tick", "counter"', '"tick", "tock"'))


def test_only_a_live_source_can_be_relayed(tmp_path):
    load(tmp_path, "a", A.replace("ticking-source", "list-source"))
    with pytest.raises(PipelineConfigError, match="'tick' is a history, and only a live source can be relayed"):
        load(tmp_path, "b", B)


def test_a_module_with_no_results_has_nothing_to_relay(tmp_path):
    load(tmp_path, "a", A.replace('"counter"', '"silent"'))
    with pytest.raises(PipelineConfigError, match="module 'silent' publishes no results to relay"):
        load(tmp_path, "b", B.replace('"counter"', '"silent"'))


def test_a_relay_of_a_relay_is_refused(tmp_path):
    load(tmp_path, "a", A)
    load(tmp_path, "b", B)
    c = B.replace('app = "b"', 'app = "c"').replace('from = "a"', 'from = "b"').replace('"tick", "counter"', '"feed"')
    with pytest.raises(PipelineConfigError, match="'feed' is itself a relay of 'a'"):
        load(tmp_path, "c", c)


def test_a_class_has_one_producer_in_a_pipeline(tmp_path):
    load(tmp_path, "a", A)
    with pytest.raises(PipelineConfigError, match="NumberResult is produced by a source and by a module"):
        load(tmp_path, "b", B.replace("[[sources]]", 'modules = ["counter"]\n\n[[sources]]'))


def test_a_pipeline_built_in_code_has_no_folder_to_find_the_owner_in():
    from pswamp_core.relay import relay_for

    with pytest.raises(PipelineConfigError, match="was not loaded from a file"):
        relay_for(None, "a", ["tick"])
