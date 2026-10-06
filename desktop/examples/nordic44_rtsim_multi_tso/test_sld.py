import importlib

# import pswamp.gui.grid_view.dim_3d.layers.lines_3 as ll
# import pswamp.gui.grid_view.dim_3d.layers.buses as bl
import pswamp.gui.grid_view.dim_3d.layers as lrs

# importlib.reload(ll)
# importlib.reload(bl)
from pswamp import database as db
from pswamp import load_config
from pswamp.gui.grid_view.dim_3d.base_plot import GridBasePlot3D

importlib.reload(db)
importlib.reload(lrs)
from pyqtgraph import Vector

# %%


if __name__ == "__main__":

    # %%
    config = load_config("examples/nordic44_rtsim_multi_tso//config_no.toml")
    config["model_data_path"]
    config["streaming"]["bootstrap_servers"] = "localhost:40162"
    from pswamp.test_utils import runners
    runners.create_database(config)

    data = {}
    import json
    from pswamp.models.reader import replace_data_lists_with_dataframes
    if 'model_data_path' in config:
        with open(config['model_data_path']) as file:
            model_data = json.load(file)
        replace_data_lists_with_dataframes(model_data)
        data["model"] = model_data

    data["model"]["bus"]
        

    from pswamp.database import get_from_database
    from pswamp.utils.misc import lookup_strings
    bus_data = get_from_database(config["database"], "bus")
    line_data = get_from_database(config["database"], "line")
    f_ix, f_mask = lookup_strings(line_data["from_bus"], bus_data["name"], return_mask=True)
    t_ix, t_mask = lookup_strings(line_data["to_bus"], bus_data["name"], return_mask=True)
    line_data[~(f_mask*t_mask)]

    trafo_data = get_from_database(config["database"], "trafo")
    f_ix, f_mask = lookup_strings(trafo_data["from_bus"], bus_data["name"], return_mask=True)
    t_ix, t_mask = lookup_strings(trafo_data["to_bus"], bus_data["name"], return_mask=True)
    trafo_data[~(f_mask*t_mask)]

    # %% 





    import sys
    sys.path.append("examples/nordic44_rtsim_multi_tso")
    from sim import create_sim
    ps = create_sim()
    from tops.simulator import Simulator
    sim = Simulator(ps)
    from pswamp.test_utils.pmu_rtsim_to_kafka import PMUPublisher
    sim.interface_quitters = {}
    pmus = PMUPublisher(rts=sim, stations=config["pmus"]["stations"])
    pmus.initialize(pmus.get_init_data(sim))
    from queue import Queue
    pmus.pmu.pmu.client_buffers = [Queue()]
    pmus.pmu.pmu.clients = [None]
    pmus.update(pmus.read_input_signal(sim))
    pmu_data_frame = pmus.pmu.pmu.client_buffers[0].get()
    print(len(pmu_data_frame.cfg.get_station_name()))
    # pmu_data_frame.cfg.get_station_name()
    
    from pswamp.test_utils import runners
    runners.run_nqkafka_server(config, run_in_process=False)
    runners.create_topics(config)

    from pswamp.models.line import Line
    line_mdl = Line(config["database"], meas_data=pmu_data_frame)
    

    from pswamp.streaming import Producer
    prod = Producer(**config["streaming"])

    import time
    def pmu_publisher():
        while True:
            prod.send(config["topics"]["pmudata"], pmu_data_frame)
            time.sleep(1)

    import threading
    thr = threading.Thread(target=pmu_publisher)
    thr.start()

        
    
    
    import pyqtgraph as pg
    app = pg.mkQApp()
    grid_plot = GridBasePlot3D()


    # import threading
    # import time
    # def myfun():
    #     while True:
    #         # print(grid_plot.window.cameraPosition())
    #         print(grid_plot.window.cameraParams())
    #         time.sleep(1)

    # thr = threading.Thread(target=myfun)
    # thr.start()

    grid_plot.window.setCameraParams(
        center=Vector(17.045048, 124.537788, 0.000000),
        distance=37.458945002967866,
        fov=60,
        elevation=41.19999999999993,
        azimuth=-89.40000000000003,
    )

    grid_plot.window.show()
    # buses_layer = BusesLayer(grid_plot, config, geo=False)
    line_layer = lrs.LineLayer(grid_plot, config, sld_id="geo")
    import numpy as np
    bus_z = np.zeros(len(bus_data))
    bus_ix = 10
    print(bus_data["name"][bus_ix])
    bus_z[bus_ix] += 1
    line_layer.set_node_z(bus_z)
    # lines_layer = lrs.LinesFreq(grid_plot, config, sld_id="geo")

    bus_layer = lrs.BusesLayer(grid_plot, config, sld_id="geo")
    bus_layer = lrs.BusNamesLayer(grid_plot, config, sld_id="geo")
    # countries_layer = bl.BusesLayer(grid_plot, config, sld_id="geo")

    tables = ["bus", "line", "trafo"]
    model_data = {table: db.get_from_database(config["database"], table) for table in tables}
    app.exec()