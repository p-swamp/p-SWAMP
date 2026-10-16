"""``pswamp deps update``'s report: lockfile parsing, direct vs transitive, and held-back rows."""

import json

import pytest
from typer.testing import CliRunner

from pswamp_tools import deps_report, main

UV_BEFORE = """\
version = 1

[[package]]
name = "fastapi"
version = "0.115.6"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "numpy"
version = "2.4.6"

[[package]]
name = "numpy"
version = "2.5.2"

[[package]]
name = "starlette"
version = "0.41.0"

[[package]]
name = "gone"
version = "1.0"
"""

UV_AFTER = UV_BEFORE.replace('version = "0.115.6"', 'version = "0.115.9"').replace(
    'version = "0.41.0"', 'version = "0.42.0"'
).replace('name = "gone"\nversion = "1.0"', 'name = "typing-extensions"\nversion = "4.15.0"')

PYPROJECT = """\
[project]
name = "x"
dependencies = ["fastapi>=0.115.6,<0.116", "NumPy[extra]>=2"]

[dependency-groups]
dev = ["Typing_Extensions>=4", { include-group = "other" }]
"""


def test_uv_lock_versions_are_read_and_forks_joined():
    assert deps_report.read_lock(UV_BEFORE, is_npm=False) == {
        "fastapi": "0.115.6",
        "numpy": "2.4.6, 2.5.2",
        "starlette": "0.41.0",
        "gone": "1.0",
    }


def test_direct_names_come_from_dependencies_and_groups_normalised():
    assert deps_report.read_direct(PYPROJECT, is_npm=False) == {"fastapi", "numpy", "typing-extensions"}


def test_npm_lock_collapses_nested_copies_and_skips_the_root():
    lock = json.dumps(
        {
            "packages": {
                "": {"name": "client", "version": "0.0.0"},
                "node_modules/react": {"version": "19.1.0"},
                "node_modules/a/node_modules/react": {"version": "18.3.1"},
                "node_modules/linked": {"link": True},
            }
        }
    )
    assert deps_report.read_lock(lock, is_npm=True) == {"react": "18.3.1, 19.1.0"}
    manifest = json.dumps({"dependencies": {"react": "^19"}, "devDependencies": {"vite": "^8"}})
    assert deps_report.read_direct(manifest, is_npm=True) == {"react", "vite"}


def test_the_delta_lists_direct_changes_and_counts_transitive_ones():
    lines = deps_report.version_delta(UV_BEFORE, UV_AFTER, [PYPROJECT], is_npm=False)
    text = "\n".join(lines)
    assert "fastapi" in text and "0.115.6 -> 0.115.9" in text
    assert "typing-extensions" in text and "added 4.15.0" in text
    assert "starlette" not in text  # transitive: counted, not listed
    assert "direct:     1 upgraded, 1 added, 0 removed" in text
    assert "transitive: 1 upgraded, 0 added, 1 removed" in text


def test_verbose_lists_the_transitive_changes():
    text = "\n".join(deps_report.version_delta(UV_BEFORE, UV_AFTER, [PYPROJECT], is_npm=False, verbose=True))
    assert "(transitive) starlette" in text and "0.41.0 -> 0.42.0" in text
    assert "(transitive) gone" in text and "removed (was 1.0)" in text


def test_nothing_moved_says_so():
    assert "nothing moved" in deps_report.version_delta(UV_BEFORE, UV_BEFORE, [PYPROJECT], is_npm=False)[0]


def test_held_back_keeps_only_the_latest_rows_without_tree_glyphs():
    output = (
        "pswamp-server v0.1.0\n"
        "├── fastapi v0.115.14 (latest: v0.120.0)\n"
        "├── uvicorn[standard] v0.38.0\n"
        "└── pydantic v2.12.0 (latest: v2.13.1)\n"
    )
    assert deps_report.held_back(output) == [
        "  fastapi v0.115.14 (latest: v0.120.0)",
        "  pydantic v2.12.0 (latest: v2.13.1)",
    ]


@pytest.mark.parametrize("command", [["deps"], ["deps", "update"]], ids=" ".join)
def test_help_renders(command):
    result = CliRunner().invoke(main.app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output


def test_an_unknown_target_is_refused():
    result = CliRunner().invoke(main.app, ["deps", "update", "--target", "major"])
    assert result.exit_code == 2
