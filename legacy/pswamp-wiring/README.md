# pswamp-wiring (transitional)

The example data sources of the server data architecture. They used to sit
beside the modules in `modules/pswamp_modules/`; they are not module code, so
when every module became its own project in `modules/<name>/` they moved here,
unchanged, as a portion of the `pswamp_modules` namespace:

- `src/pswamp_modules/sources/`: the sample recording and the synthetic live
  feed, named in a pipeline file's `[[sources]]` (`pipelines/<app>.toml`) and
  in `<APP>_DATA_CLIENTS`
  (`sample:pswamp_modules.sources.sample_client:SampleRecordingClient`).
- `tests/`: their tests, run by `uv run pswamp test server`.

The pipeline declarations that were here too are now data, one TOML file per
app in `pipelines/` at the repo root.

**This project is removed by the refactoring that follows:** the sources
become modules in `modules/`. Don't add anything here that is not a source; a
new module goes in `modules/<name>/` (`uv run pswamp new module`).
