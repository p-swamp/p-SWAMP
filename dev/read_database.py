import importlib
import sqlite3
from pathlib import Path

import pandas as pd
from synchrophasor.simplePMU import SimplePMU

import pswamp.database as db
import pswamp.models as model_lib
import pswamp.utils.pypmu as pypmu_utils
from pswamp import load_config
from pswamp.utils.interactive_python import fix_paths_if_interactive

importlib.reload(db)
importlib.reload(model_lib)
importlib.reload(pypmu_utils)

fix_paths_if_interactive("examples")


#TODO: Make a test out of this


if __name__ == "__main__"    :
    # config = load_config()

    
    # config = {
    #     "database": {
    #         "type": "sqlite", "file_path": Path("data/grid_database.db")
    #     }}

    # config = {
    #     "database": {
    #         "type": "file", "file_path": Path("data/model_data.json")
    #     }}

    config = {
        "database": {"type": "sqlite", "file_path": "file::memory:?cache=shared", "uri": True}
    }
    
    con = sqlite3.connect("file::memory:?cache=shared", uri=True)

    for field in ["line", "bus"]:
        try:
            con.cursor().execute(f"DROP TABLE {field}")
        except sqlite3.OperationalError:
            continue
    df = pd.DataFrame(
        columns=["name", "from_bus", "to_bus"],
        data=[["L5304-5305-1", "5304", "5305"]]
    ).to_sql("line", con)

    pd.DataFrame(
        columns=["name", "V_n"],
        data=[["5304", 420], ["5305", 420]]
    ).to_sql("bus", con)

    data = db.get_from_database(config["database"], "bus")
    
    pmu = SimplePMU(
        "",
        0,
        station_names=["5304", "5307"],
        channel_names=[
            ["V", "I[L5304-5305-1]"],
            ["V", "I[L5304-5305-1]"],
        ],
    )
    dataframe = pmu.generate_dataframe()
    dataframe.cfg.get_station_name()
    
    phasor_ext = pypmu_utils.PMUPhasorExtractor(
        wanted_stations=["5304", "5305"],
        wanted_channels=[
            ["V", "I[L5304-5305-2]"],
            ["V", "V2"]
        ], dataframe=dataframe)
    
    phasor_ext
    
    phasor_ext.get(dataframe.get_phasors())
    phasor_ext.idx
    

    line_mdl = model_lib.line.Line(config["database"], dataframe, units=["L5304-5305-1"])
    print(line_mdl.V_from(dataframe))
    print(line_mdl.V_to(dataframe))
    
    

    fmt = {
        "line": {
            "I_from": {
                "type": "phasor",
                "station": "{from_bus}",
                "channel": "I[{name}]"
            },
            "I_to": {
                "station": "{to_bus}",
                "channel": "I[{name}]"
            }
        },
        "bus": {
            "V": {
                "type": "phasor",
                "station": "{name}",
                "channel": "V"
            },
            "freq": {
                "type": "freq",
                "station": "{name}"
            }
        },
        "load": {
            "I": {
                "station": "{from_bus}"
                "channel": "I[{unit}"
            }
        }
    }
    unit_name = "L5304-5305-1"
    
    current_phasor_extractor_from = pypmu_utils.PMUPhasorExtractor(
        wanted_stations=["5304"],
        wanted_channels=[[f'I[{unit_name}]']], dataframe=dataframe
    )
    current_phasor_extractor_from.get(dataframe.get_phasors())