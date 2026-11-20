# Start it

With the [tools installed](what-you-need.md), one command starts everything.

## 1. Start the server

In a terminal, in the `p-SWAMP` folder:

```shell
uv run pswamp dev server
```

The first time, this builds the application, which takes several minutes.
After that it starts in seconds. The terminal then shows the server's log, and
stays busy for as long as p-SWAMP runs.

You will know it is ready when the log stops scrolling and shows lines such as
`Application startup complete`.

## 2. Open it

Open <http://127.0.0.1:8000> in your browser. You should see the **Monitor**:
a map of the Nordic 44 test grid in the middle, and panels beside it for
frequency, status, alarms, phasors and line outages.

The monitor replays a 70-second recording from the beginning each time you open
it. About half a minute in, a line trips: watch the map and the alarms.

The [tour](tour.md) explains what each page shows.

## 3. Stop it

Go back to the terminal and press ++ctrl+c++. p-SWAMP stops, and nothing it
did is kept: the next start begins from scratch. That is on purpose, so you can
experiment freely.

## If something goes wrong

**The page does not load.** Wait until the log says `Application startup
complete`; the first build is slow. Check that nothing else on your computer
already uses port 8000.

**The CIM graph page says the grid is loading.** On first use, p-SWAMP
downloads the Nordic 44 grid model from the internet. Give it a minute; it is
kept for the next start.

**`pswamp dev server` cannot find Docker or Podman.** Start Docker Desktop or
Podman Desktop first, then run the command again.

## Next

- [Take the tour](tour.md) of what p-SWAMP shows.
- [Run an analysis from a script](from-a-script.md), with no server at all.
