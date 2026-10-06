import matplotlib.pyplot as plt
import pandas as pd
import pswamp.database as db
import pswamp.visualization.components.single_line_diagram as sld
from io import StringIO
import ezdxf
# from ezdxf import colors
# from ezdxf.enums import TextEntityAlignment
import sqlite3


if __name__ == "__main__":
    
    # %%
    # Create a new DXF document.
    doc = ezdxf.new(dxfversion="R2010")

    msp = doc.modelspace()

    # Add entities to a layout by factory methods: layout.add_...() 
    msp.add_line((0, 0), (20, 0))  # , dxfattribs={"color": colors.YELLOW})
    msp.add_line((20, 0), (10, 20))  # , dxfattribs={"color": colors.YELLOW})
    msp.add_line((0, 0), (10, 20))  # , dxfattribs={"color": colors.YELLOW})
    msp.add_mtext("B1").set_location((0, 0))
    msp.add_mtext("B2").set_location((20, 0))
    msp.add_mtext("B3").set_location((10, 20))

    f = StringIO()
    doc.write(f)
    
    fout = StringIO(f.getvalue())
    doc = ezdxf.read(fout)
    
    sld.SCALING_FACTOR = 1
    sld.get_buses(doc, ["B1", "B2", "B3"])

    config = {
        "database": {"type": "sqlite", "file_path": "file::memory:?cache=shared", "uri": True},
        "single_line_diagrams": {
            "sld1": {
                "countries": ["Norway", "Sweden", "Denmark", "Finland"],
                "aspect_ratio": 2,
            }
        }
    }
    con = sqlite3.connect("file::memory:?cache=shared", uri=True)
    # %%
    # Remove previous tables (if present)
    for field in ["line", "bus", "single_line_diagrams"]:
        try:
            con.cursor().execute(f"DROP TABLE {field}")
        except sqlite3.OperationalError:
            continue

    # Add new bus and line data
    pd.DataFrame(
        columns=["name", "from_bus", "to_bus"],
        data=[
            ["L1-2", "B1", "B2"],
            ["L2-3", "B2", "B3"],
            ["L1-3", "B1", "B3"]
        ],
    ).to_sql("line", con)

    pd.DataFrame(
        columns=["name", "V_n"],
        data=[
            ["B1", 420],
            ["B2", 420],
            ["B3", 420],
        ],
    ).to_sql("bus", con)

    cursor = con.cursor()
    cursor.execute("""CREATE TABLE "single_line_diagrams" ("name" TEXT, "data"	BLOB);""")
    cursor.execute(f"""INSERT INTO "single_line_diagrams" (name, data) VALUES ('sld1', '{f.getvalue()}')""")
    con.commit()
    # %%

    data = db.get_from_database(config["database"], "single_line_diagrams")
    data.iloc[-1]
    
    fout = StringIO(data["data"][0])
    doc = ezdxf.read(fout)
    
    bus_data = db.get_from_database(config["database"], "bus")
    line_data = db.get_from_database(config["database"], "line")
    sld.SCALING_FACTOR = 1
    # TODO: How to deal with it when some buses are missing in the SLD?
    buses, bus_coords = sld.get_buses(doc, bus_data["name"])
    line_coords, midpoints = sld.get_branches_xy_by_matching_buses(doc, line_data)

    [plt.plot(lc[:, 0], lc[:, 1]) for lc in line_coords]
    plt.scatter(bus_coords[:, 0], bus_coords[:, 1])
    plt.show()
    # %%
    import numpy as np

    # %%
    from pswamp.gui.grid_view.dim_2d.base_plot import GridBasePlot2D
    # import pswamp.gui.grid_view.dim_2d.layers.lines_2 as ll
    # import pswamp.gui.grid_view.dim_2d.layers.buses as bl
    import pswamp.gui.grid_view.dim_2d.layers as lrs
    import importlib
    # importlib.reload(ll)
    # importlib.reload(bl)
    importlib.reload(db)
    importlib.reload(lrs)

    dir(lrs)
    
    import pyqtgraph as pg
    app = pg.mkQApp()
    grid_plot = GridBasePlot2D()
    grid_plot.window.show()
    # buses_layer = BusesLayer(grid_plot, config, geo=False)
    line_layer = lrs.LineLayer(grid_plot, config, sld_id="sld1")
    bus_layer = lrs.BusesLayer(grid_plot, config, sld_id="sld1")
    bus_layer = lrs.BusNamesLayer(grid_plot, config, sld_id="sld1")
    # countries_layer = bl.BusesLayer(grid_plot, config, sld_id="sld1")

    tables = ["bus", "line", "trafo"]
    model_data = {table: db.get_from_database(config["database"], table) for table in tables}
    app.exec()

    # %%

    config["streaming"] = {
        "type": "nqkafka",
        "bootstrap_servers": "localhost: 50000",
        "consumers_seek_to_beginning": True
    }
    config["streaming"]
    # from nqkafka import NQKafkaServer
    # nqkafka_server = NQKafkaServer(config["streaming"]["bootstrap_servers"], run_in_process=False)
    # nqkafka_server.start_server()
    from pswamp.test_utils import runners
    from pswamp.streaming.base import Consumer, Producer

    runners.run_nqkafka_server(config, run_in_process=False)
    runners.create_topic("pmudata", config["streaming"])
    
    # %%
    consumer = Consumer(**config["streaming"], topic="pmudata")
    producer = Producer(**config["streaming"])
    
    from synchrophasor.simplePMU import SimplePMU
    pmu = SimplePMU(
        "",
        0,
        station_names=["B1", "B2", "B3"],
        channel_names=[
            ["V", "I[L1-2]", "I[L1-3]"],
            ["V", "I[L1-2]", "I[L2-3]"],
            ["V", "I[L1-3]", "I[L2-3]"],
        ],
    )
    

    # %%
    import time

    def produce_msgs():
        i_msg = 0
        n_msgs = 10
        while True:
            if i_msg > n_msgs:
                print("Done publishing messages.")
                break
            i_msg += 1

            dataframe = pmu.generate_dataframe()
            producer.send(topic="pmudata", msg=dataframe)
            time.sleep(0.1)

    import threading
    producer_thread = threading.Thread(target=produce_msgs)
    producer_thread.start()

    msg = next(iter(consumer))
    msg.value.get_freq()

    # %%
    dataframe = pmu.generate_dataframe()

    import  pswamp.models as model_lib
    bus_mdl = model_lib.bus.Bus(
        config["database"], dataframe)

    # %%
    importlib.reload(lrs)

    config["topics"] = {"pmudata": "pmudata"}

    app = pg.mkQApp()
    grid_plot = GridBasePlot2D()
    grid_plot.window.show()
    # buses_layer = BusesLayer(grid_plot, config, geo=False)
    line_layer = lrs.LineLayer(grid_plot, config, sld_id="sld1")
    bus_layer = lrs.BusesLayer(grid_plot, config, sld_id="sld1")
    bus_names_layer = lrs.BusNamesLayer(grid_plot, config, sld_id="sld1")
    phasors_layer = lrs.PhasorPlotLayer(grid_plot, config, sld_id="sld1")
    # countries_layer = bl.BusesLayer(grid_plot, config, sld_id="sld1")
    

    app.exec()