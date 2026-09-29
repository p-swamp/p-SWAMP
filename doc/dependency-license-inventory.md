# Dependency license inventory

Inventory date: 2026-09-25.

This is engineering input to the dependency policy, not legal advice. License
metadata can be incomplete or wrong; reciprocal and commercial alternatives
need qualified review before the project relies on them.

## Scope and method

The inventory covers the dependency inputs committed to this repository:

- `app/client-web/package-lock.json`: 572 npm package records, including
  transitive and platform-specific optional packages;
- `e2e/package-lock.json`: 6 npm package records;
- root `uv.lock` and `app/server-python/uv.lock`: 82 unique registry package and
  version pairs, plus four commit-pinned Git dependencies; and
- actions referenced by `.github/workflows/*.yml`.

npm licenses come directly from each exact package record in the lockfiles.
Python locks do not store license metadata, so the registry-backed results use
the exact locked version's PyPI metadata. Commit-pinned Git dependencies use the
license file at the locked commit. Broad legacy Python classifiers are reported
as broad classifiers rather than guessed into a more specific SPDX license.

This does not inventory Debian packages in the Docker base images. Dependency
Review does not inspect those; the planned image scan is the appropriate check.

## Current distribution and obligations

As of the inventory date, this repository publishes source code on GitHub but
does not publish a Python package, container image, desktop executable or other
built distribution. CI builds a container only for testing and discards it, so
the dependencies inventoried below create no current redistribution obligation.

Before publishing the current container image or publicly serving the web
client, address these concrete gaps:

- Copy this project's Apache-2.0 `LICENSE` into the runtime image. The current
  Dockerfile copies the project source but not its license.
- Add the Geist copyright notice and full OFL-1.1 text to the Vite output, and
  make it easily accessible from the served application (for example through a
  third-party notices page). Vite copies the unmodified font files from
  `node_modules` into `dist/`, but not the font's `LICENSE`; the final Docker
  stage copies only `dist/` from the Node build stage. No source disclosure or
  font-name change is required for this unmodified use.
- Generate and include notices for the third-party JavaScript and CSS bundled
  into the Vite output. Minification currently preserves Tailwind's short
  license banner, but not complete notices for the other runtime libraries.
- Preserve the license files installed with Python distributions in their
  `.dist-info` directories and the base image's system-package notices.

Lightning CSS, `caniuse-lite` and `type-fest` are build inputs absent from the
final image unless a future build copies their code or data into an output.
Run a fresh license/SBOM scan on the final image before publication, since this
source inventory does not cover Debian packages or prove the contents of a
future image.

## npm results

The web client lock contains these declarations:

| License expression | Package records | Notes |
| --- | ---: | --- |
| MIT | 477 | Predominant application and build-tool license |
| ISC | 26 | Permissive |
| MPL-2.0 | 24 | `lightningcss` plus platform binaries; review required |
| Apache-2.0 | 19 | Permissive with notice and patent terms |
| BSD-2-Clause | 11 | Permissive |
| BSD-3-Clause | 8 | Permissive |
| BlueOak-1.0.0 | 2 | `isexe`, `minimatch`; permissive |
| 0BSD | 1 | Permissive |
| CC-BY-4.0 | 1 | `caniuse-lite` browser data; attribution required if the data is redistributed |
| OFL-1.1 | 1 | Geist font; notice required if the font files are redistributed |
| Python-2.0 | 1 | Permissive Python license |
| CC0-1.0 | 1 | `type-fest`; permissive |

The npm `dev` marker describes how npm installs a package, not whether code from
that package reaches the browser. The generated output was inspected to settle
that question: it contains Geist font files, but no identifiable Lightning CSS,
`caniuse-lite` or `type-fest` payload. Lightning CSS transforms CSS in the web
build stage, but its executable is not copied into the final server image.

### Browser-delivered dependencies

These obligations apply when the built web client is served to users, because
browsers receive copies of its JavaScript, CSS and font files. The service
distributing this web client must therefore make the required notices
readily accessible to its users.

An instrumented Vite production build on the inventory date found the following
packages contributing bytes to the browser-delivered files:

| License | Browser-delivered packages or assets |
| --- | --- |
| MIT | `react`, `react-dom`, `scheduler`, `react-router`, `@radix-ui/react-compose-refs`, `@radix-ui/react-slot`, `clsx`, `tailwind-merge`, `uplot`, Tailwind-generated CSS and `tw-animate-css` |
| Apache-2.0 | `class-variance-authority` |
| ISC | `lucide-react` |
| OFL-1.1 | Geist `.woff2` font files |

The JavaScript and CSS licenses are permissive and require preservation of their
applicable notices whenever those files are delivered; they do not require
publishing this application's source. The Geist font may be embedded and served
under OFL-1.1, provided the delivered application includes its copyright notice
and the OFL text. A generated, served `THIRD_PARTY_NOTICES` file can satisfy
these notice requirements if it contains the required text and is readily
available to recipients.

The build inspection excludes development and transformation tools that do not
contribute bytes to the browser output, including Vite, Lightning CSS,
`caniuse-lite`, `type-fest`, TypeScript and ESLint.

## Python results

The exact registry package versions group as follows. The two NumPy and SciPy
versions are lock alternatives for different supported Python versions.

| Declared license | Exact locked packages |
| --- | --- |
| Apache-2.0 | `asttokens`, `kafka-python`, `pytest-asyncio`, `tzdata` |
| Apache-2.0 OR BSD-2-Clause | `packaging` |
| BSD-2-Clause | `pygments` |
| BSD-3-Clause | `click`, `idna`, `ipython`, `matplotlib-inline`, `networkx`, `psutil`, `python-dotenv`, `starlette`, `uvicorn`, `websockets` |
| BSD classifier only | `colorama`, `contourpy`, `cycler`, `ipython-pygments-lexers`, `kiwisolver`, `nodeenv`, `numpy-dynamic-array`, `pandas`, `prompt-toolkit`, `pyopengl`, `qtrangeslider`, `scipy` 1.17.1 and 1.18.1, `traitlets` |
| ISC | `pexpect`, `ptyprocess` |
| MIT | `annotated-doc`, `annotated-types`, `anyio`, `cfgv`, `fastapi`, `filelock`, `fonttools`, `httptools`, `identify`, `iniconfig`, `platformdirs`, `pre-commit`, `pydantic`, `pydantic-core`, `pyparsing`, `pyqtgraph`, `pyshp`, `pytest`, `ruff`, `tomli`, `typing-inspection`, `virtualenv`, `wcwidth` |
| MIT classifier only | `executing`, `ezdxf`, `h11`, `jedi`, `nfoursid`, `parso`, `pluggy`, `pure-eval`, `python-discovery`, `pyyaml`, `six`, `stack-data`, `watchfiles` |
| MIT-CMU | `pillow` |
| MPL-2.0 AND MIT | `tqdm`; review required because both licenses apply |
| PSF-2.0 | `distlib`, `matplotlib`, `typing-extensions` |
| Apache-2.0 OR BSD-3-Clause | `python-dateutil` (legacy classifiers) |
| Apache-2.0 OR MIT | `uvloop` (legacy classifiers) |
| BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | `numpy` 2.4.6 and 2.5.2; includes bundled components |
| EPL-2.0 OR BSD-3-Clause | `paho-mqtt`; source distribution is dual licensed |
| LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only OR commercial | `pyside6`, `pyside6-addons`, `pyside6-essentials`, `shiboken6`; alternatives, not cumulative requirements |

The commit-pinned Git dependencies are:

| Package | Locked commit | License | Scope |
| --- | --- | --- | --- |
| `synchrophasor` (`hallvar-h/pypmu`) | `e16662c` | BSD-3-Clause | Desktop base; excluded from the web image |
| `nqkafka` | `0a90ea2` | MIT | Desktop `[full]` extra |
| `tops-rt` | `f6fe1a4` | MIT | Desktop `[full]` extra |
| `tops` | `5c6e777` | MIT | Transitive through `tops-rt` |

The web server runtime has no MPL, EPL, LGPL or GPL dependency. Those findings
are in the desktop `[full]` extra, except MPL-2.0 in the web build chain. Python
development dependencies in the two locks use permissive licenses.

## GitHub Actions

The workflows reference `actions/checkout`, `actions/setup-node`,
`actions/upload-artifact`, `actions/dependency-review-action`,
`astral-sh/setup-uv`, `docker/setup-buildx-action` and
`docker/build-push-action`. Their repository licenses are MIT or Apache-2.0,
which are already allowed. GitHub recognizes workflow `uses:` entries as
dependencies when Dependency Graph is enabled.

## Policy result

The allowlist contains the observed permissive software licenses, including
`BSD-2-Clause-Views` for `uri-js` and `HPND-Markus-Kuhn` for `wcwidth`, plus
`CC-BY-4.0` for browser compatibility data and `OFL-1.1` for the font. Two
additional entries are explicit exceptions based on GitHub's SBOM
classification: `JSON` for `json-schema-typed`, whose "Good, not Evil"
restriction is not an ordinary open-source permission, and
`LicenseRef-scancode-matplotlib-1.3.0`, a custom identifier in Matplotlib's
compound license expression.

The allowlist currently accepts MPL-2.0, including the Lightning CSS build
dependency, but does not pre-approve EPL-2.0, LGPL or GPL. Existing dependencies
are a baseline; Dependency Review evaluates additions and changes, so an update
involving one of the latter licenses will stop for explicit review. Allowlisting
a license is a dependency-admission policy, not evidence that redistribution
obligations have been satisfied.

Unknown licenses are reported by GitHub but do not fail Dependency Review. The
Python packages with broad or alternative metadata above should therefore also
be checked in the first real pull-request run against GitHub's own license
classification.
