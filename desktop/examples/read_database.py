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

    # In-memory SQLite database:
    config = {
        "database": {"type": "sqlite", "file_path": "file::memory:?cache=shared", "uri": True}
    }
    con = sqlite3.connect("file::memory:?cache=shared", uri=True)

    # Remove previous tables (if present)
    for field in ["line", "bus"]:
        try:
            con.cursor().execute(f"DROP TABLE {field}")
        except sqlite3.OperationalError:
            continue

    # Add new bus and line data
    pd.DataFrame(
        columns=["name", "from_bus", "to_bus"],
        data=[
            ["L5304-5305-1", "5304", "5305"],
            ["L5305-5304-1", "5305", "5304"]
        ]
    ).to_sql("line", con)

    pd.DataFrame(
        columns=["name", "V_n"],
        data=[["5304", 420], ["5305", 420]]
    ).to_sql("bus", con)

    # Retrieve data
    data = db.get_from_database(config["database"], "bus")

    # SQL queries to retrieve data from database
    cursor = con.cursor()
    cursor.execute("SELECT name FROM bus WHERE name In (SELECT from_bus FROM line)")
    cursor.fetchall()
    
    # Create some PMU data frames
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
    
    # Utility to extract channels from PMU data frame. Lookup of strings in
    # __init__ to get indices of wanted channels, and using indices for 
    # retrieving values
    phasor_ext = pypmu_utils.PMUPhasorExtractor(
        wanted_stations=["5304", "5305"],
        wanted_channels=[
            ["V", "I[L5304-5305-2]"],
            ["V", "V2"]
        ], dataframe=dataframe)
        
    phasor_ext.get(dataframe.get_phasors())
    phasor_ext.idx
    

    # Using model data and PMU data frame for doing calculations based on
    # component models. Note: The models assume that the channels in the PMU
    # data frame are named in a specific way.
    line_mdl = model_lib.line.Line(config["database"], dataframe, units=["L5304-5305-1"])
    print(line_mdl.V_from(dataframe))
    print(line_mdl.V_to(dataframe))