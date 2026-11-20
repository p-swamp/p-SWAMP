# Contributing

Contributions are welcome: a bug report, a fix, a new module, a page of
documentation. This page is how to make one.

## Setting up

You need [git](https://git-scm.com/downloads), [uv](https://docs.astral.sh/uv/)
and, to run the web application, Docker or Podman (see
[what you need](../start/what-you-need.md)). To work on the web client you
also need [Node.js 24](https://nodejs.org/).

```shell
git clone https://github.com/p-swamp/p-SWAMP.git
cd p-SWAMP
uv sync                                  # every Python project, into ./.venv
git config core.hooksPath .githooks      # the pre-push checks, once per clone
```

Then:

```shell
uv run pswamp dev server     # the server on http://127.0.0.1:8000 (one terminal)
uv run pswamp dev client     # the web client with hot reload on :5173 (another)
uv run pswamp docs serve     # this documentation, with live reload, on :8001
```

`uv run pswamp --help` lists every command; each has its own `--help`.

## Before opening a pull request

```shell
uv run pswamp check          # the static checks: lock, lint, types, pipelines, api contract
uv run pswamp test server    # the unit tests
uv run pswamp docs build     # the documentation, --strict
```

CI runs the same commands on every pull request, so running them first saves
a round trip. The pre-push hook runs `pswamp check` for you.

If you changed an endpoint or a message the server sends to the browser,
regenerate the api contract and commit it with the change:

```shell
uv run pswamp api generate
```

## Signing off your commits (DCO)

Every commit must carry a `Signed-off-by:` line naming its author, to certify
the [Developer Certificate of Origin](https://developercertificate.org/): that
you wrote the change, or otherwise have the right to submit it under the
project's licence. Add it with `-s`:

```shell
git commit -s -m "feat(frame-stats): report the median frequency"
```

The pull request check rejects a commit without one, and so does the pre-push
hook. To sign off the commits already on your branch:
`git rebase --signoff main`.

## How changes are written

- **Commits explain the change**, in the
  [Conventional Commits](https://www.conventionalcommits.org/) style the history
  uses (`feat(recorder): ...`, `fix(core): ...`, `docs: ...`), with a body that
  says why.
- **A decision that is expensive to reverse gets an ADR** in `doc/adr/`: see
  [architecture decisions](../adr/README.md).
- **AGENTS.md is the developer handbook**: the conventions, and the reasons for
  them, for people and coding agents alike. Read the section for the part you
  are changing.
- **AI coding assistants are welcome**, and AGENTS.md is written for them too.
  You remain responsible for what you submit: understand it, test it, and sign it
  off yourself.

## Adding a module

A new analysis is a module, and starts from the generator:

```shell
uv run pswamp new module peak-frequency "Peak frequency"
```

It writes a working module, its tests, an example script, a pipeline and a page,
and adds the module to the [Modules](../modules/index.md) page. The
[module cookbook](../module-cookbook.md) takes it from there.

## Writing documentation

The site is built from `doc/`, plus a few files that live beside what they
describe:

| To change | Edit |
|---|---|
| a page of the general documentation | `doc/<page>.md` |
| a module's page | `modules/<name>/README.md`, and its optional `docs/` folder |
| a module's API page | the docstrings in its code (Google style: `Args:`, `Returns:`, `Raises:`) |
| what a module is for, in plain words | its line in `doc/modules/index.md` |
| the site's navigation, theme or plugins | `mkdocs.yml` |

Links between files are written as on GitHub, relative to the file; the build
points each one at the page on the site, or at the file on GitHub when it is
code. `uv run pswamp docs build` fails on a broken link. Every page has an
**Edit this page** button that opens its source.

Write for the reader of the page: the Getting started and Concepts pages for
someone who is not a software engineer, the developer pages for a developer.

## Reporting a problem

Open an issue on [GitHub](https://github.com/p-swamp/p-SWAMP/issues) with what
you did, what you expected, and what happened.

## Code of conduct

Contributors follow the
[LF Projects Code of Conduct](https://lfprojects.org/policies/code-of-conduct/).
