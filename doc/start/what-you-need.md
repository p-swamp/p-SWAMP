# What you need

p-SWAMP runs on Windows, macOS and Linux. To try it you need three things:
a copy of the code, a tool that runs Python projects, and a tool that runs
containers. This page takes you through each, once. It takes about fifteen
minutes, most of it waiting for downloads.

## 1. Git, to get the code

[Git](https://git-scm.com/downloads) downloads the code and keeps it up to
date. Install it, then open a terminal (on Windows, *Terminal* or *PowerShell*)
and run:

```shell
git clone https://github.com/p-swamp/p-SWAMP.git
cd p-SWAMP
```

You now have a folder called `p-SWAMP`. Every command on these pages is run
from inside it.

## 2. uv, to run the Python parts

[uv](https://docs.astral.sh/uv/getting-started/installation/) installs the
right version of Python and everything p-SWAMP needs, in a folder of its own,
without touching anything else on your computer. Follow its installation page,
then check it works:

```shell
uv run pswamp --help
```

The first run takes a minute: uv downloads Python and p-SWAMP's libraries. You
should then see the list of `pswamp` commands. `pswamp` is p-SWAMP's own
command line; every task on these pages is one of its commands.

## 3. Docker or Podman, to run the application

The web application runs in containers: the server, a message broker and a
graph database, started together. Install one of:

- [Docker Desktop](https://docs.docker.com/get-docker/), or
- [Podman Desktop](https://podman-desktop.io/).

Either works; p-SWAMP finds whichever is installed. Start it once after
installing, so it is running in the background.

!!! tip "If a command says a tool is missing"

    `pswamp` checks for every tool it needs before it starts, and names the one
    that is missing with a link to install it. Install it, open a new terminal,
    and run the command again.

## Next

[Start p-SWAMP](first-run.md) and open it in your browser.
