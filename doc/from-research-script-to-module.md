# From a research script to a p-SWAMP module

This is the workflow for bringing a new analysis into p-SWAMP, such as voltage
stability monitoring, OPF or oscillation monitoring. It is meant for researchers
who bring the algorithm and core contributors who integrate it.

The starting point is a researcher with a promising algorithm in a Python
script: it loads a CSV or runs a simulation, applies the algorithm to the data,
and plots the results. The researcher knows the power-system side well, knows
basic Python, and has little experience with large code bases or git.

The goal is that the researcher spends their time on the algorithm, not on
rebases, merge conflicts or the server stack.

`doc/module-cookbook.md` is the technical recipe for writing a module. This
document is about **who does what, and when**.

## The main idea: researchers stay out of the shared files

Merge conflicts and rebase trouble only come from editing files that other
people also edit. In p-SWAMP those are:

- `uv.lock`
- `pipelines/grid-monitor.toml`
- `docker-compose.yml` and `k8s/`
- `app/server-python/src/server.py` and `app/client-web/src/App.tsx`
- `doc/api/openapi.json` and `app/client-web/src/api/schema.ts`

A module's own code lives in two folders that nobody else touches:

- `modules/<name>/`
- `models/src/pswamp_models/<pkg>/`

So the workflow is built on three rules:

1. **The researcher works in a sandbox outside the repo until the algorithm
   works.** No git is needed there.
2. **A core contributor does the promotion into the repo.** This is the one
   step that touches the shared files.
3. **After that, the researcher only edits their own module folder**, in small
   pull requests that are squash-merged.

## The stages at a glance

| Stage | Who | Where | Git needed? |
|---|---|---|---|
| 0. The research script | Researcher | Anywhere | No |
| 1. Turn the script into a function and a golden test | Researcher | Prototype sandbox | No |
| 2. Wrap the function as a module | Researcher | Prototype sandbox | No |
| 3. Promotion into the repo | Core contributor, pairing with the researcher | p-SWAMP repo | Yes (core contributor) |
| 4. Further work on the module | Researcher | `modules/<name>/` in the repo | One fixed recipe |

## Stage 0: The research script

The researcher's script stays as it is: data in, algorithm, plot out. Keep it.
It is the reference that everything later is checked against.

## Stage 1: Turn the script into a function (sandbox, no git)

The researcher copies the prototype sandbox. A preliminary version is at
<https://github.com/hallvar-h/p-SWAMP-prototype>. It installs p-SWAMP as a
dependency and gives them a grid, simulated PMU and SCADA measurements, and a
module skeleton. Its `README.md` explains how to set it up and use it.

In the sandbox, they split their script into two parts:

1. **A pure function for the algorithm.** It takes numpy arrays (for example a
   time window of measurements) and returns numbers. It does no file reading
   and no plotting.
2. **A golden test.** Run the original script once, save its output, and write
   a test asserting that the function reproduces it.

The golden test is the bridge between "the researcher's result" and "the
engineered module". It moves into the repo with the module, and it keeps
catching regressions after the researcher has moved on.

Stage 1 deals with the hardest conceptual step first. A script processes a
whole file at once; a module gets one frame at a time. Doing the split on the
researcher's own data, before any p-SWAMP concepts appear, keeps the two
problems apart.

## Stage 2: Wrap it as a module (sandbox, still no git)

- Fill in `module.py` and `messages.py` in the sandbox. Keep `process()` a thin
  adapter: it collects frames into a buffer (see
  `doc/module-time-window-notes.md`) and calls the pure function from Stage 1.
- Run it with `OfflineSim` in `scripts/offline_run.py`: trip a line, run the
  module, plot.
- Run it on the real-time live source with `scripts/live_run.py`. This also
  shows whether it keeps up at 50 frames/s.
- Optionally, run it in the full stack with no change to the repo:

  ```
  uv run pswamp dev server --extra-modules ../<sandbox>
  ```

  A result body with a `status` field (`OK`, `Alert`, `Emergency`) puts the
  module in the grid monitor's Status panel straight away.

### Ready for promotion

The module is ready for Stage 3 when all of these hold:

- [ ] The golden test passes.
- [ ] The module imports only `pswamp_core`, `pswamp_models` and third-party
      libraries (numpy, scipy, ...). It never imports `pswamp_proto`, another
      module or anything from `app/`.
- [ ] What it publishes is a pydantic `DataModel` with a pinned `version`, and
      the result body has a `status` field.
- [ ] A short `README.md` covers what the module reads, what it emits, its
      parameters, and its physical assumptions and limits.

## Stage 3: Promotion (core contributor, pairing with the researcher)

This takes about an hour. A core contributor does it, ideally with the
researcher watching, on a short-lived branch from a freshly pulled `main`:

1. `uv run pswamp new module <name> "<Label>"`.
2. Copy `module.py` and `messages.py` into the generated files, fix the
   imports, and add the module's third-party dependencies to
   `modules/<name>/pyproject.toml`.
3. Move the tests into `modules/<name>/tests/` as `test_<pkg>_module.py`, the
   golden test among them.
4. To run it on the live grid, add it to `pipelines/grid-monitor.toml` and to
   the module worker's list in `docker-compose.yml` and `k8s/base/p-swamp.yaml`.
5. Run `uv lock`, `uv run pswamp api generate`, `uv run pswamp check` and
   `uv run pswamp test module <name>`, then open a pull request.

The prototype's README, "Promoting it into p-SWAMP", has the details.

Conflicts in generated files are resolved by regenerating, never by merging by
hand: `uv lock` for `uv.lock`, and `uv run pswamp api generate` for
`openapi.json` and `schema.ts`.

In the same pull request, add a line to `CODEOWNERS` making the researcher the
owner of `modules/<name>/`. That makes the boundary explicit, and sends them
the reviews of changes to their module.

Panels and pages (`LiveGrid.handle`, a React panel) stay with the core
contributors. The page the generator writes is enough to start with.

## Stage 4: Further work on the module (researcher, one git recipe)

From here on the researcher edits only `modules/<name>/` and, when the results
change, `models/src/pswamp_models/<pkg>/`. One recipe covers every change:

```
git switch main
git pull
git switch -c <name>/short-description

# edit only modules/<name>/ (and its models)
uv run pswamp test module <name>

git commit -s -am "What changed"
git push -u origin HEAD
# then open a pull request on GitHub
```

Rules that keep this simple:

- **Pull requests are squash-merged.** The branch's history doesn't matter, so
  there is never a reason to rebase.
- **If GitHub says the branch is behind `main`, click "Update branch".** It
  merges `main` in; no rebase is needed.
- **If anything gets confusing, start over.** Copy the module folder somewhere
  safe, make a fresh branch from `main` with the recipe above, and copy the
  folder back. This always works, because nobody else edits that folder.
- **Keep pull requests small and short-lived**, a few days at most. Long-lived
  branches are where conflicts come from, even in your own folder.
- **Sign off every commit.** `-s` adds the `Signed-off-by:` line that the DCO
  check requires. In VS Code, set `git.alwaysSignOff` to `true` so it happens
  by itself. Activate the pre-push hook once with
  `git config core.hooksPath .githooks`; it catches a missing sign-off before
  the push.

This differs on purpose from the advice in
`doc/how-the-core-contributors-work-together.md` to rebase long-lived branches
daily. Researchers should not have long-lived branches, so they never need
rebase.

## What the core contributors provide

The workflow only holds if the sandbox is stable and easy to start from:

1. **Merge the extra-modules hook into `main`** (`feature/extra-modules-hook`),
   and point the prototype at tagged releases of `main` rather than a feature
   branch. Researchers should depend on a released contract, not a moving
   branch.
2. **Make the offline simulation a supported API.** The prototype's
   `OfflineSim` uses private internals of `rtsim-from-cim` (`engine`, `pmu`,
   `scada`), so a refactor there breaks every researcher's sandbox without
   warning. Moving it into p-SWAMP (for example as `rtsim_from_cim.offline`)
   keeps the prototype a thin template rather than a second code base.
3. **Add a CSV-to-`PmuFrame` helper**, so that researchers can run their module
   on their own recorded data in Stage 2, not only on the simulated grid.
4. **Test the sandbox template in CI**, as `pswamp check-generators` tests the
   generators, so that a change to the `Module` contract that breaks the sandbox
   fails here and not on a researcher's laptop.
5. **Consider a `pswamp new prototype <name> <dir>` command** that writes the
   sandbox already renamed. Renaming `my-module`, `my_module` and `MyModule` by
   hand is an error-prone first task.
6. **Move the sandbox to the project's GitHub organisation and make it a
   template repository**, so that starting one is a button click. The
   preliminary version is in a personal account,
   <https://github.com/hallvar-h/p-SWAMP-prototype>.
