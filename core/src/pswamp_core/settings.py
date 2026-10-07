# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Configuring a component from the environment.

A deployment names a component class with a spec, ``name:module.path:Class``,
and configures it with a block of variables prefixed by that name::

    PSWAMP_TRANSPORT=kafka:pswamp_core.transport.kafka:KafkaTransport
    KAFKA_BOOTSTRAP_SERVERS=kafka:9092

A ``Configurable`` class declares the variables it reads in ``env_settings``,
and ``from_env(name)`` builds it from them. The transport and data providers
are configured this way, so a deployment can plug in its own class with one
package and a few variables, and no code change here.
"""

from __future__ import annotations

import importlib
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar, Literal, TypeVar

__all__ = [
    "Configurable",
    "EnvSetting",
    "MissingSettingError",
    "env_key",
    "load_class",
    "parse_setting",
    "parse_specs",
    "read_setting",
]


class MissingSettingError(RuntimeError):
    """A setting is missing or malformed, or a spec does not name a usable class."""


@dataclass(frozen=True)
class EnvSetting:
    """One variable a component reads: ``{NAME}_{setting}``.

    The lower-cased ``setting`` is the constructor keyword ``from_env`` passes.
    """

    setting: str
    description: str
    required: bool = False
    default: str | None = None
    kind: Literal["str", "int", "float", "seconds", "list", "path"] = "str"


def env_key(name: str, setting: str) -> str:
    """The variable for ``setting`` of the component called ``name``: ``live``,
    ``PATH`` → ``LIVE_PATH``."""
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return f"{prefix}_{setting.upper()}"


def parse_setting(key: str, setting: EnvSetting, raw: str) -> Any:
    """``raw`` parsed per ``setting.kind``. ``key`` names the variable in the
    error a malformed value raises."""
    try:
        if setting.kind == "int":
            return int(raw)
        if setting.kind == "float":
            return float(raw)
        if setting.kind == "seconds":
            return timedelta(seconds=float(raw))
        if setting.kind == "list":
            return [item.strip() for item in raw.split(",") if item.strip()]
        if setting.kind == "path":
            return Path(raw)
        return raw
    except ValueError as error:
        raise MissingSettingError(f"{key} must be a valid {setting.kind}: {raw!r}") from error


def read_setting(name: str, setting: EnvSetting) -> Any:
    """The value of one declared setting, parsed per its ``kind``; its default,
    or ``None``, when unset."""
    key = env_key(name, setting.setting)
    raw = os.environ.get(key, "").strip() or setting.default
    if raw is None:
        if setting.required:
            raise MissingSettingError(f"{key} is required to configure {name!r}")
        return None
    return parse_setting(key, setting, raw)


class Configurable:
    """A component built from its ``{NAME}_{SETTING}`` variables."""

    env_settings: ClassVar[tuple[EnvSetting, ...]] = ()

    @classmethod
    def from_env(cls, name: str, **overrides: Any):
        """``cls(name=name, **settings)``, reading every declared setting that
        ``overrides`` does not supply."""
        settings: dict[str, Any] = {}
        for setting in cls.env_settings:
            keyword = setting.setting.lower()
            if keyword not in overrides:
                value = read_setting(name, setting)
                if value is not None:
                    settings[keyword] = value
        return cls(name=name, **settings, **overrides)


def parse_specs(variable: str, spec: str) -> list[tuple[str, str, str]]:
    """``name:module.path:Class`` entries, comma-separated, as triples."""
    specs = []
    for entry in (item.strip() for item in spec.split(",")):
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 3 or not all(parts):
            raise MissingSettingError(f"{variable}: {entry!r} is not name:module.path:Class")
        specs.append((parts[0], parts[1], parts[2]))
    if not specs:
        raise MissingSettingError(f"{variable} names nothing")
    return specs


C = TypeVar("C")


def load_class(variable: str, module_path: str, class_name: str, base: type[C]) -> type[C]:
    """Import ``class_name`` from ``module_path`` and check it is a ``base``."""
    try:
        module = importlib.import_module(module_path)
    except ImportError as error:
        raise MissingSettingError(f"{variable}: cannot import {module_path!r}: {error}") from error
    cls = getattr(module, class_name, None)
    if not (isinstance(cls, type) and issubclass(cls, base)):
        raise MissingSettingError(f"{variable}: {module_path}.{class_name} is not a {base.__name__}")
    return cls
