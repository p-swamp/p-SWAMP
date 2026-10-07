# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Pipeline files: an app's pipeline as data, ``pipelines/<app>.toml``.

::

    app = "pmu-test-streamer"
    modules = ["frame-stats", "excursion", "range-summary"]   # pswamp.modules entry points

    [[sources]]                                               # in order; the first is the default
    name = "sample"
    module = "sample-replay"                                  # a source module's entry point

    [enrich]
    cim_reference = "n44-cim-stub"                            # "none": no reference

``load_pipeline(path)`` (also ``Pipeline.load``) reads one into a ``Pipeline``:

- **Modules and sources are found by name**, through the ``pswamp.modules``
  entry points every module project declares; a name nothing installs is an
  error listing the names that are installed. An entry point's name is its
  module's ``name``. A source is a module too (a
  ``pswamp_core.sources.SourceModule``, which runs in its run's process, not
  in a host): ``module = "sample-replay"`` names one, instanced under the
  source's ``name``.
- **Sources stay configurable from the environment.** The set of sources is
  built on every call: ``<APP>_SOURCES`` (``name:entry-point,...``), when set,
  replaces the file's sources; ``<APP>_CIM_REFERENCE`` overrides
  ``enrich.cim_reference``; and each source reads its own ``{NAME}_{SETTING}``
  block (``LIVE_PATH`` for the source named ``live``). ``<APP>`` is the app's
  name upper-cased, dashes as underscores (``PMU_TEST_STREAMER``). (The
  ``<APP>_DATA_CLIENTS`` variable of the old data clients is gone, and an
  error says so if it is still set.)
- **Everything ``Pipeline`` checks, plus one thing**: every class a module
  reads has a producer in the pipeline: a source's ``model`` (its primary
  output), a module's output, or the run itself (``PlayerStatus``,
  ``ErrorEvent``, ``PipelineClosed``).

``PipelineConfig`` is the file's schema. It is configuration, not a message,
so it lives here and not in ``pswamp_models``.

Run as ``python -m pswamp_core.pipeline_config modules`` or ``... validate
PATH...``: what ``uv run pswamp modules list`` and ``pswamp pipelines
validate`` call.
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .enrich import CimReferenceEnricher
from .settings import MissingSettingError, env_key
from .sources import SourceModule, SourceSet

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

    from .modules import Module
    from .pipeline import Pipeline

__all__ = [
    "MODULES_GROUP",
    "ConfiguredSources",
    "PipelineConfig",
    "PipelineConfigError",
    "available_modules",
    "load_pipeline",
    "resolve_entry",
    "resolve_module",
]

#: The entry-point group a module project registers its module in.
MODULES_GROUP = "pswamp.modules"

_SLUG = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"


class PipelineConfigError(ValueError):
    """A pipeline file is unreadable, malformed, or names something unusable."""


class SourceConfig(BaseModel):
    """One source: a name, and the source module that serves it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", description="The source's name: what a run switches to.")
    module: str = Field(pattern=_SLUG, description="The source module, by its pswamp.modules entry-point name.")


class EnrichConfig(BaseModel):
    """What every record from the sources gets on its way to the pipeline."""

    model_config = ConfigDict(extra="forbid")

    cim_reference: str | None = Field(default=None, description='The CIM reference id; "none" or absent: no reference.')


class PipelineConfig(BaseModel):
    """The schema of ``pipelines/<app>.toml``."""

    model_config = ConfigDict(extra="forbid")

    app: str = Field(pattern=_SLUG, description="The app's name: its topics' namespace and its variables' prefix.")
    modules: list[str] = Field(default_factory=list, description="Module entry-point names.")
    sources: list[SourceConfig] = Field(min_length=1, description="The sources, the default first.")
    enrich: EnrichConfig = Field(default_factory=EnrichConfig)

    @model_validator(mode="after")
    def _unique(self) -> PipelineConfig:
        for what, names in (("module", self.modules), ("source", [s.name for s in self.sources])):
            twice = sorted({name for name in names if names.count(name) > 1})
            if twice:
                raise ValueError(f"{what} {', '.join(twice)} listed twice")
        return self

    def build(self) -> Pipeline:
        """The ``Pipeline`` this declares: modules resolved, every check run."""
        from .pipeline import Pipeline

        installed = available_modules()
        modules = tuple(resolve_module(name, installed) for name in self.modules)
        sources = ConfiguredSources(
            app=self.app,
            default_sources=",".join(f"{s.name}:{s.module}" for s in self.sources),
            cim_reference=self.enrich.cim_reference,
        )
        return Pipeline(self.app, sources, modules=modules, source_models=sources.source_models())


@dataclass(frozen=True)
class ConfiguredSources:
    """A pipeline file's ``SourceSet`` factory. Reads the environment on every
    call, so a deployment's ``<APP>_SOURCES`` and ``{NAME}_{SETTING}`` apply."""

    app: str
    #: The file's sources, as an ``<APP>_SOURCES`` value.
    default_sources: str
    cim_reference: str | None = None

    @property
    def sources_variable(self) -> str:
        return env_key(self.app, "SOURCES")

    @property
    def cim_variable(self) -> str:
        return env_key(self.app, "CIM_REFERENCE")

    def source_specs(self) -> list[tuple[str, str]]:
        """``(name, entry point)`` per source, the environment's if set.

        Raises ``PipelineConfigError`` when the retired ``<APP>_DATA_CLIENTS``
        is still set, or a value is not ``name:entry-point``."""
        legacy = env_key(self.app, "DATA_CLIENTS")
        if os.environ.get(legacy, "").strip():
            raise PipelineConfigError(
                f"{legacy} is no longer read: sources are modules now. "
                f"Set {self.sources_variable}=name:entry-point,... instead, e.g. "
                f"{self.sources_variable}=sample:sample-replay,live:live-synthetic "
                "(the entry-point names are listed by `uv run pswamp modules list`)"
            )
        spec = os.environ.get(self.sources_variable, "").strip() or self.default_sources
        specs = []
        for entry in (item.strip() for item in spec.split(",")):
            if not entry:
                continue
            name, _, module = entry.partition(":")
            if not name or not module or ":" in module:
                raise PipelineConfigError(f"{self.sources_variable}: {entry!r} is not name:entry-point")
            specs.append((name, module))
        if not specs:
            raise PipelineConfigError(f"{self.sources_variable} names nothing")
        return specs

    def source_classes(self) -> list[tuple[str, type[SourceModule]]]:
        """``(name, class)`` per source, the classes resolved through the entry points."""
        installed = available_modules()
        classes = []
        for name, module in self.source_specs():
            cls = resolve_entry(module, installed)
            if not issubclass(cls, SourceModule):
                raise PipelineConfigError(f"{self.sources_variable}: {module!r} is an analysis module, not a source")
            classes.append((name, cls))
        return classes

    def source_models(self) -> tuple[type[DataModel], ...]:
        """What the sources serve (each class's ``model``), without building one."""
        return tuple(dict.fromkeys(cls.model for _, cls in self.source_classes()))

    def __call__(self) -> SourceSet:
        reference = os.environ.get(self.cim_variable, "").strip() or self.cim_reference
        enrichers = [] if reference in (None, "none") else [CimReferenceEnricher(reference)]
        return SourceSet([cls.from_env(name) for name, cls in self.source_classes()], enrichers=enrichers)


def available_modules() -> dict[str, EntryPoint]:
    """Every installed module, by entry-point name."""
    return {point.name: point for point in entry_points(group=MODULES_GROUP)}


def resolve_entry(name: str, installed: dict[str, EntryPoint] | None = None) -> type[Module]:
    """The class registered as ``name``: an analysis module or a source."""
    from .modules import Module

    installed = available_modules() if installed is None else installed
    point = installed.get(name)
    if point is None:
        known = ", ".join(sorted(installed)) or "none"
        raise PipelineConfigError(
            f"no module named {name!r} is installed (entry-point group {MODULES_GROUP}); installed: {known}"
        )
    try:
        cls = point.load()
    except Exception as error:  # an import error in the module's own code
        raise PipelineConfigError(f"module {name!r} ({point.value}) does not import: {error}") from error
    if not (isinstance(cls, type) and issubclass(cls, Module)):
        raise PipelineConfigError(f"module {name!r} ({point.value}) is not a Module (an analysis module or a source)")
    if cls.name != name:
        raise PipelineConfigError(f"module {name!r} ({point.value}) is named {cls.name!r}; the two must match")
    return cls


def resolve_module(name: str, installed: dict[str, EntryPoint] | None = None) -> type[Module]:
    """The analysis module class registered as ``name``."""
    cls = resolve_entry(name, installed)
    if issubclass(cls, SourceModule):
        raise PipelineConfigError(f"{name!r} is a source ({cls.kind}), not an analysis module")
    return cls


def load_pipeline(path: str | os.PathLike[str]) -> Pipeline:
    """Read and check the pipeline file at ``path``. Raises
    ``PipelineConfigError``, saying which file and why."""
    path = Path(path)
    try:
        # utf-8-sig: a BOM (as some Windows editors write) is not a TOML error.
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise PipelineConfigError(f"{path}: no such pipeline file (relative paths are from {Path.cwd()})") from None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PipelineConfigError(f"{path}: {error}") from error
    try:
        return PipelineConfig.model_validate(data).build()
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in e['loc']) or '(file)'}: {e['msg']}" for e in error.errors()
        )
        raise PipelineConfigError(f"{path}: {problems}") from None
    except (ValueError, MissingSettingError) as error:
        raise PipelineConfigError(f"{path}: {error}") from error


# --- what `pswamp modules list` and `pswamp pipelines validate` run --------------------


def _names(models: Sequence[type]) -> str:
    return ", ".join(model.__name__ for model in models) or "-"


def _list_modules() -> int:
    installed = available_modules()
    if not installed:
        print(f"No module is installed (entry-point group {MODULES_GROUP}).")
        return 0
    failed = 0
    for name, point in sorted(installed.items()):
        distribution = point.dist.name if point.dist is not None else "?"
        print(f"{name}  ({distribution}, {point.value})")
        try:
            cls = resolve_entry(name, installed)
        except PipelineConfigError as error:
            print(f"    error:    {error}")
            failed += 1
            continue
        if issubclass(cls, SourceModule):
            playable = "playable" if cls.commands else "not playable"
            print(f"    kind:     source ({cls.kind}, {playable})")
            print("    reads:    -")
        else:
            print("    kind:     module")
            print(f"    reads:    {_names(cls.input_models())}")
        print(f"    emits:    {_names(cls.outputs)}")
        print(f"    commands: {_names(cls.commands)}")
    return 1 if failed else 0


def _validate(paths: Sequence[str]) -> int:
    failed = 0
    for name in paths:
        try:
            pipeline = load_pipeline(name)
        except PipelineConfigError as error:
            print(f"FAIL  {error}")
            failed += 1
            continue
        sources = [source for source, _ in pipeline.sources.source_specs()]  # type: ignore[attr-defined]
        modules = ", ".join(m.name for m in pipeline.modules) or "none"
        print(f"ok    {name}: app {pipeline.app}, sources {', '.join(sources)}, modules {modules}")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pswamp_core.pipeline_config")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("modules", help="list the installed modules")
    validate = commands.add_parser("validate", help="load and check pipeline files")
    validate.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    return _list_modules() if args.command == "modules" else _validate(args.paths)


if __name__ == "__main__":
    sys.exit(main())
