# pswamp-wiring (transitional)

The pipeline declarations and the example data sources of the server data
architecture. They used to sit beside the modules in `modules/pswamp_modules/`;
they are not module code, so when every module became its own project in
`modules/<name>/` they moved here, unchanged, as two portions of the
`pswamp_modules` namespace:

- `src/pswamp_modules/pipelines/<app>.py`: one `PIPELINE` per app, imported by
  the app's web API and by the workers
  (`PSWAMP_WORKER_PIPELINES=pswamp_modules.pipelines.<app>:PIPELINE`).
- `src/pswamp_modules/sources/`: the sample recording and the synthetic live
  feed, named in `<APP>_DATA_CLIENTS`
  (`sample:pswamp_modules.sources.sample_client:SampleRecordingClient`).
- `tests/`: their tests, run by `uv run pswamp test server`.

Because the import paths did not change, `docker-compose.yml`, `k8s/` and the
server needed no edit.

**This project is removed by the refactoring that follows:** pipelines become
TOML files resolved through the `pswamp.modules` entry points, and the sources
become modules in `modules/`. Don't add anything here that is not a pipeline
or a source; a new module goes in `modules/<name>/`
(`uv run pswamp new module`).
