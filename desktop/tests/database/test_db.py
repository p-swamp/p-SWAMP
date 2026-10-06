import numpy as np
import sqlite3

import pandas as pd
from synchrophasor.simplePMU import SimplePMU

import pswamp.database as db
import pswamp.models as model_lib
import pswamp.utils.pypmu as pypmu_utils


def test_database():
    # config = load_config()

    # config = {
    #     "database": {"type": "sqlite", "file_path": Path("data/grid_database.db")}
    # }

    # config = {
    #     "database": {
    #         "type": "file", "file_path": Path("data/model_data.json")
    #     }}

    config = {
        "database": {
            "type": "sqlite",
            "file_path": "file::memory:?cache=shared",
            "uri": True,
        }
    }

    con = sqlite3.connect("file::memory:?cache=shared", uri=True)
    for field in ["line", "bus"]:
        try:
            con.cursor().execute(f"DROP TABLE {field}")
        except sqlite3.OperationalError:
            continue

    line_data = pd.DataFrame(
        columns=["name", "from_bus", "to_bus"], data=[["L5304-5305-1", "5304", "5305"]]
    )
    line_data.to_sql("line", con)

    bus_data = pd.DataFrame(columns=["name", "V_n"], data=[["5304", 420], ["5305", 420]])
    bus_data.to_sql(
        "bus", con
    )

    bus_data_retrieved = db.get_from_database(config["database"], "bus")
    line_data_retrieved = db.get_from_database(config["database"], "line")
    assert all(bus_data_retrieved == bus_data)
    assert all(line_data_retrieved == line_data)


    pmu = SimplePMU(
        "",
        0,
        station_names=["5304", "5305"],
        channel_names=[
            ["V", "I[L5304-5305-1]"],
            ["V", "I[L5304-5305-1]"],
        ],
    )
    
    phasor_data = [
        [(420, 0.1), (100, 0.2)],
        [(421, 0.3), (101, 0.4)]]
    
    dataframe = pmu.generate_dataframe(phasor_data=phasor_data)
    # dataframe.cfg.get_station_name()

    phasor_ext = pypmu_utils.PMUPhasorExtractor(
        wanted_stations=["5304", "5308"],
        wanted_channels=[["V", "I[L5304-5305-2]"], ["V", "V2"]],
        dataframe=dataframe,
    )

    retrieved_phasors = phasor_ext.get(dataframe.get_phasors())
    
    reference = [
        [(420.0, 0.10), (np.nan, np.nan)],
        [(np.nan, np.nan), (np.nan, np.nan)]]
    arr1 = np.concatenate(reference)
    arr2 = np.concatenate(retrieved_phasors)

    assert (((arr1 - arr2) < 1e-8) | (np.isnan(arr1) & np.isnan(arr2))).all()
    
    line_mdl = model_lib.line.Line(
        config["database"], dataframe, units=["L5304-5305-1"]
    )
    assert abs(420 * np.exp(1j * 0.1) - line_mdl.V_from(dataframe)) < 1e-5
    assert abs(421 * np.exp(1j * 0.3) - line_mdl.V_to(dataframe)) < 1e-5


if __name__ == "__main__":
    test_database()