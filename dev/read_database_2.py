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

    config = {
        "database": {"type": "sqlite", "file_path": "file::memory:?cache=shared", "uri": True}
    }
    
    con = sqlite3.connect("file::memory:?cache=shared", uri=True)
    # %%
    for field in ["line", "bus", "pmu"]:
        try:
            con.cursor().execute(f"DROP TABLE {field}")
        except sqlite3.OperationalError:
            continue
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

    pd.DataFrame(
        columns=["name", "bus"],
        data=[["PMU1", "5304"], ["PMU2", "5304"]]
    ).to_sql("pmu", con)
    #
    # data = db.get_from_database(config["database"], "bus")
    # pmu_data = db.get_from_database(config["database"], "pmu")

    cursor = con.cursor()
    # cursor.execute("SELECT name FROM pmu WHERE bus In (SELECT from_bus FROM line)")
    # cursor.execute("SELECT * FROM pmu WHERE bus In(SELECT from_bus FROM line)")
    # cursor.execute("SELECT to_bus FROM line")

    # """SELECT Title, Name
    # FROM albums
    # INNER JOIN artists ON artists.ArtistId = albums.ArtistId;"""
    #
    cursor.execute(
        """SELECT *
        FROM line
        LEFT JOIN pmu ON line.to_bus = pmu.bus;"""
    )
    from pprint import pprint
    pprint(cursor.fetchall())
    # print([d[0] for d in cursor.description])
    # %%

    
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