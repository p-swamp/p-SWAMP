# Data licensing

p-SWAMP's code is **Apache-2.0**. Some of the data it uses is not, and the
difference matters if you reuse it.

## The Nordic44 grid model is downloaded, never shipped

The live grid simulation and the CIM graph page use, by default, the
[Nordic44 test model](https://github.com/statnett/Nordic44) published by
Statnett. p-SWAMP does not ship it: [LazyCIM](https://github.com/p-swamp/LazyCIM)
downloads it on first use, into a cache on your machine.

!!! warning "CC BY-NC-SA 4.0"

    - **BY**: attribute it: *Nordic44 test model, Statnett SF*.
    - **NC**: non-commercial use only.
    - **SA**: derivatives must carry the same licence.

    Full terms: <https://creativecommons.org/licenses/by-nc-sa/4.0/>

For anything commercial, point p-SWAMP at a grid of your own
(`PSWAMP_CIM_PATH`, a folder of CGMES files), or at the small sample grid that
ships with p-SWAMP's core (`core/src/pswamp_core/cim/sample_grid/`), which is
part of the source.

## Recordings in the repository

Three files in the repository hold *simulated* data from a Nordic 44 test
system, produced with the TOPS power system simulator:

| File | What it is |
|---|---|
| `app/server-python/src/pswamp_web/data/n44_line_trip_50hz.npz` | The 70-second recording the monitor replays: a line trip and its reconnection. |
| `app/server-python/src/pswamp_web/data/n44_grid_geometry.json` | Where the monitor draws each station and line of that system. |
| `modules/sample-replay/src/pswamp_modules/sample_replay/sample_data.txt` | The three-second sample recording (and its copy in `live-synthetic`). |

They are simulations, not measurements of a real grid. Figures and screenshots
on this site made from them say so in their captions.

## Map tiles

The CIM graph page draws its map with tiles from
[OpenStreetMap](https://www.openstreetmap.org/copyright). Map data ©
OpenStreetMap contributors, available under the Open Database Licence. The map
on that page and in its screenshot carries the attribution.
