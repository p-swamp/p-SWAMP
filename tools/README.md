# pswamp-tools

The `pswamp` command line: the repo's automation as one Typer CLI that runs
natively on Windows, macOS and Linux.

    uv run pswamp --help

The help text of every command and group is the documentation. Helpers shared by
the commands live in `src/pswamp_tools/_*.py` (repo root discovery, running
tools with clear "not installed" errors, docker/podman detection, rich output).
