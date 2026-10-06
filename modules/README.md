# pswamp-modules

The analysis modules of the p-SWAMP server data architecture, the pipelines
that put them together, and the example data sources.
`doc/server-data-architecture.md` describes the architecture;
`doc/module-cookbook.md` is the recipe for a new module.

- Modules: `pswamp_modules/<module>/` (`module.py`, re-exported by `__init__.py`)
- Pipelines: `pswamp_modules/pipelines/<app>.py`
- Example sources: `pswamp_modules/sources/`
- Tests: a `tests/` package beside the code it tests
  (`pswamp_modules/<module>/tests/test_module.py`), run by
  `uv run pswamp test server` (`-k <module>` for one module's)

A module is one folder: its code and its tests. Adding, removing or reviewing
a module touches that folder (and, for a new pipeline, one file in
`pipelines/`). The `tests/` folders are kept out of the image by
`.dockerignore`.

The package sits directly in this folder, with no `src/` level (unlike
`core/`): `module-root = ""` in `pyproject.toml`.

## Rules

- **It depends on `pswamp-core` and nothing else in this repo.** Nothing here
  imports the web backend (`app/server-python/src/`) or the desktop package
  (`pswamp`). `pswamp_modules/tests/test_layering.py` checks it.
- **`pswamp-core` imports nothing from here.**
- **The web backend imports from here**: an app's `api.py` takes its pipeline,
  its result classes and its commands from this package.

So a worker (`python -m pswamp_core.worker`) hosts a module with core and
modules alone, from any working directory.

## Adding a module

`uv run pswamp new module <slug> "<Label>"` writes the
module folder (code and tests) and its pipeline here, and its web API and page
in `app/`.
