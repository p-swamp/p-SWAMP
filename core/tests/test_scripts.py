"""pswamp_core.scripts: a module or a source by its entry-point name, as a script names it."""

from __future__ import annotations

import pytest
from support import ListSource, frame, install_modules
from test_modules import Halver

from pswamp_core.pipeline_config import PipelineConfigError
from pswamp_core.scripts import module, source


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    install_modules(monkeypatch, **{"list-source": "support:ListSource", "halver": "test_modules:Halver"})


def test_a_source_is_made_by_its_name_with_its_arguments():
    frames = [frame(0.0), frame(0.05)]
    made = source("list-source", frames=frames)
    assert isinstance(made, ListSource) and list(made.read()) == frames


def test_a_module_is_made_by_its_name():
    assert isinstance(module("halver"), Halver)


def test_a_module_is_not_a_source():
    with pytest.raises(TypeError, match="'halver' is a module, not a source"):
        source("halver")


def test_a_name_nothing_provides_lists_what_is_installed():
    with pytest.raises(PipelineConfigError, match="'rtsim-from-cim'.* installed: halver, list-source"):
        source("rtsim-from-cim")
