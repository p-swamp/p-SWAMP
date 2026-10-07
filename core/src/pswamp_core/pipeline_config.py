# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Pipeline files: an app's pipeline as data, ``pipelines/<app>.toml``.

::

    app = "pmu-test-streamer"
    modules = ["frame-stats", "excursion", "range-summary"]   # pswamp.modules entry points

    [[sources]]                                               # in order; the first is the default
    name = "sample"
    client = "pswamp_modules.sources.sample_client:SampleRecordingClient"

    [enrich]
    cim_reference = "n44-cim-stub"                            # "none": no reference

``load_pipeline(path)`` (also ``Pipeline.load``) reads one into a ``Pipeline``:

- **Modules are found by name**, through the ``pswamp.modules`` entry points
  every module project declares; a name nothing installs is an error listing
  the names that are installed. An entry point's name is its module's
  ``name``.
- **Sources stay configurable from the environment.** The gateway is built
  as before, on every call: ``<APP>_DATA_CLIENTS``
  (``name:module.path:Class,...``), when set, replaces the file's sources;
  ``<APP>_CIM_REFERENCE`` overrides ``enrich.cim_reference``; and each client
  reads its own ``{NAME}_{SETTING}`` block. ``<APP>`` is the app's name
  upper-cased, dashes as underscores (``PMU_TEST_STREAMER``).
- **Everything ``Pipeline`` checks, plus one thing**: every class a module
  reads has a producer in the pipeline: a source's ``model``, a module's
  output, or the run itself (``PlayerStatus``, ``ErrorEvent``, ``PipelineClosed``).

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

from .datagateway import CimReferenceEnricher, DataClient, DataGateway, gateway_from_env
from .settings import MissingSettingError, env_key, load_class, parse_specs

if TYPE_CHECKING:
    from pswamp_models.common import DataModel

    from .modules import Module
    from .pipeline import Pipeline

__all__ = [
    "MODULES_GROUP",
    "ConfiguredGateway",
    "PipelineConfig",
    "PipelineConfigError",
    "available_modules",
    "load_pipeline",
    "resolve_module",
]

#: The entry-point group a module project registers its module in.
MODULES_GROUP = "pswamp.modules"

_SLUG = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"


class PipelineConfigError(ValueError):
    """A pipeline file is unreadable, malformed, or names something unusable."""


class SourceConfig(BaseModel):
    """One source: a name, and the data client that serves it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", description="The source's name: what a run switches to.")
    client: str = Field(pattern=r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$", description="The data client, module.path:Class.")


class EnrichConfig(BaseModel):
    """What the gateway adds to every record."""

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
        gateway = ConfiguredGateway(
            app=self.app,
            default_clients=",".join(f"{s.name}:{s.client}" for s in self.sources),
            cim_reference=self.enrich.cim_reference,
        )
        return Pipeline(self.app, gateway, modules=modules, source_models=gateway.source_models())


@dataclass(frozen=True)
class ConfiguredGateway:
    """A pipeline file's gateway factory. Reads the environment on every call,
    so a deployment's ``<APP>_DATA_CLIENTS`` and ``{NAME}_{SETTING}`` apply."""

    app: str
    #: The file's sources, as an ``<APP>_DATA_CLIENTS`` value.
    default_clients: str
    cim_reference: str | None = None

    @property
    def clients_variable(self) -> str:
        return env_key(self.app, "DATA_CLIENTS")

    @property
    def cim_variable(self) -> str:
        return env_key(self.app, "CIM_REFERENCE")

    def client_specs(self) -> list[tuple[str, str, str]]:
        """``(name, module.path, Class)`` per source, the environment's if set."""
        spec = os.environ.get(self.clients_variable, "").strip() or self.default_clients
        return parse_specs(self.clients_variable, spec)

    def source_models(self) -> tuple[type[DataModel], ...]:
        """What the sources serve (each client class's ``model``), without
        building a client."""
        return tuple(
            dict.fromkeys(
                load_class(self.clients_variable, module, cls, DataClient).model
                for _, module, cls in self.client_specs()
            )
        )

    def __call__(self) -> DataGateway:
        reference = os.environ.get(self.cim_variable, "").strip() or self.cim_reference
        enrichers = [] if reference in (None, "none") else [CimReferenceEnricher(reference)]
        return gateway_from_env(self.clients_variable, self.default_clients, enrichers=enrichers)


def available_modules() -> dict[str, EntryPoint]:
    """Every installed module, by entry-point name."""
    return {point.name: point for point in entry_points(group=MODULES_GROUP)}


def resolve_module(name: str, installed: dict[str, EntryPoint] | None = None) -> type[Module]:
    """The module class registered as ``name``."""
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
        raise PipelineConfigError(f"module {name!r} ({point.value}) is not a Module")
    if cls.name != name:
        raise PipelineConfigError(f"module {name!r} ({point.value}) is named {cls.name!r}; the two must match")
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
            cls = resolve_module(name, installed)
        except PipelineConfigError as error:
            print(f"    error:    {error}")
            failed += 1
            continue
        # Every entry point is an analysis module for now: sources are still
        # data clients, named in a pipeline's [[sources]], not entry points.
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
        sources = [source for source, _, _ in pipeline.gateway.client_specs()]  # type: ignore[attr-defined]
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
