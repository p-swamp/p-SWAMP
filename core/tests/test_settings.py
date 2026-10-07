"""Configuring components from the environment: settings and specs."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from pswamp_core.settings import Configurable, EnvSetting, MissingSettingError, env_key, parse_specs, read_setting


class Thing(Configurable):
    env_settings = (
        EnvSetting("URL", "Where", required=True),
        EnvSetting("TIMEOUT", "How long", default="2", kind="seconds"),
        EnvSetting("HOSTS", "Which", kind="list"),
        EnvSetting("FILE", "What", kind="path"),
        EnvSetting("RETRIES", "How often", default="3", kind="int"),
    )

    def __init__(self, name, url, timeout, retries, hosts=None, file=None):
        self.name, self.url, self.timeout, self.retries, self.hosts, self.file = name, url, timeout, retries, hosts, file


def test_a_setting_is_prefixed_by_the_component_s_name():
    assert env_key("remote-data", "url") == "REMOTE_DATA_URL"


def test_from_env_reads_and_parses_the_declared_settings(monkeypatch):
    monkeypatch.setenv("MY_THING_URL", "http://x")
    monkeypatch.setenv("MY_THING_HOSTS", "a, b")
    monkeypatch.setenv("MY_THING_FILE", "/tmp/f")
    thing = Thing.from_env("my-thing")
    assert (thing.url, thing.timeout, thing.retries) == ("http://x", timedelta(seconds=2), 3)
    assert (thing.hosts, thing.file) == (["a", "b"], Path("/tmp/f"))
    assert Thing.from_env("my-thing", url="http://override").url == "http://override"


def test_a_missing_or_malformed_setting_is_an_error(monkeypatch):
    with pytest.raises(MissingSettingError, match="OTHER_URL"):
        Thing.from_env("other")
    monkeypatch.setenv("BAD_TIMEOUT", "soon")
    with pytest.raises(MissingSettingError):
        read_setting("bad", Thing.env_settings[1])


def test_specs_are_name_module_class_triples():
    assert parse_specs("V", "a:m.n:C, b:x:Y") == [("a", "m.n", "C"), ("b", "x", "Y")]
    for bad in ("", "a:b", "a::C"):
        with pytest.raises(MissingSettingError):
            parse_specs("V", bad)
