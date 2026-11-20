# How this site is built

This site is [MkDocs](https://www.mkdocs.org/) with the
[Material](https://squidfunk.github.io/mkdocs-material/) theme, styled like
[LazyCIM's documentation](https://p-swamp.github.io/LazyCIM/). It is built from
the repository on every pull request and published from `main` to GitHub
Pages.

## Locally

```shell
uv run pswamp docs serve     # http://127.0.0.1:8001, rebuilt on every edit
uv run pswamp docs build     # into site/, --strict, as CI builds it
```

The builders are the `docs` dependency group of `pswamp-tools`
(`tools/pyproject.toml`). `pswamp docs` installs it on first use; a plain
`uv sync` leaves it out, and the container image never has it.

## What it is built from

| Source | Becomes |
|---|---|
| `doc/**/*.md` | the pages at the same path (`doc/start/tour.md` is `start/tour/`) |
| `modules/<name>/README.md` | the module's overview, `modules/<name>/` |
| `modules/<name>/docs/` | the module's further pages and images |
| the docstrings of `core/`, `models/` and each module | the API reference pages |
| `doc/api/openapi.json` | the Web API page |
| `tools/README.md`, `modules/README.md`, `k8s/README.md` | pages under *For developers* |

Kept off the site: `doc/WIP-*.md` (working notes meant to be deleted) and the
ADR template.

The machinery is in `tools/docs_site/`:

- `layout.py` is the one table of which file becomes which page.
- `gen_pages.py` (run by mkdocs-gen-files) writes the pages that do not live in
  `doc/`: the collected READMEs, each module's section and API page, the messages
  reference, the Web API page and the navigation of the folders that list
  themselves.
- `hooks.py` resolves every relative link against the file it was written in,
  and points it at the page on the site, or at the file on GitHub when it is
  code. It also keeps the navigation files (`SUMMARY.md`) off the site.
- `rst_literals.py` (a griffe extension) renders the docstrings' RST literal
  blocks (`Example::` and an indented block) as code.

## Strict, on every pull request

`.github/workflows/docs.yml` builds the site with `--strict` on every pull
request, so a broken link, a reference that does not resolve or a module the
Modules page does not mention fails the check. The built site is attached to
the run as the `site-preview` artifact, to download and read. There are no
per-pull-request preview URLs; that would need a second host.

## Publishing

A push to `main` builds the site again and publishes it with GitHub's own Pages
actions (`actions/upload-pages-artifact`, `actions/deploy-pages`), not by
pushing to a `gh-pages` branch.

This needs, once, in the repository's settings: **Settings → Pages → Build and
deployment → Source: GitHub Actions**. Restrict the `github-pages` environment
to `main` as well (**Settings → Environments → github-pages**), so that only a
merge publishes.

The site is public, whether or not the repository is.

## Where the address is written

The site's address, `https://p-swamp.github.io/p-SWAMP/`, is written in:

- `mkdocs.yml` (`site_url`),
- `CONTRIBUTING.md`,
- `README.md`,
- `doc/module-cookbook.md`.

If the site moves, change them together. GitHub Pages addresses are
case-sensitive.

## Versions

There is one version of the site, the one on `main`. Per-release versions (with
[mike](https://github.com/jimporter/mike)) can be added when p-SWAMP makes
releases that users stay on.

## The MkDocs ecosystem is moving

Material for MkDocs announces its end of life on 5 May 2027, with critical fixes
until then, and names [Zensical](https://zensical.org/), from the same team, as
its successor; it reads an existing `mkdocs.yml`. Some plugins also print a
notice recommending ProperDocs, a continuation of MkDocs 1.x. `pswamp docs`
silences both notices. Plan the move to Zensical before May 2027, once the
plugins this site relies on (mkdocstrings, gen-files, literate-nav, neoteroi)
work with it.
