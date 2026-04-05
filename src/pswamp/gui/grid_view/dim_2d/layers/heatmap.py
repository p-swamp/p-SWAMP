# LICENSE HEADER MANAGED BY add-license-header
#
# Copyright 2026 NTNU/SINTEF/Statnett SF
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import numpy as np
# import threading
# from pswamp.utils.pmu_time_window import PMUTimeWindow
# from PySide6 import QtCore, QtGui, QtWidgets
# import pyqtgraph as pg
# from pswamp.visualization.components.phasor_plot import PhasorPlot
# from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations
from pswamp.visualization.components.heatmap import HeatMap as HeatMapBasePlot
# import time
# import uuid
# from pswamp.utils.pmu_time_window import PMUTimeWindowOnline
from pswamp.app_templates.snapshot_app import SnapshotApp
import threading
import ezdxf
from io import StringIO
from pswamp.database import get_from_database
import numpy as np
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindow
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.components.phasor_plot import PhasorPlot
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations
import pswamp.visualization.components.single_line_diagram as sld
from pswamp.gui.grid_view.exceptions import LayerFailedException
from pswamp import models as model_lib


class FrequencyHeatMap:
    def __init__(self, parent, config, sld_id=None, geo=True, heatmap_kwargs=dict(
            y_scale=1, lims=[-0.035, 0.035], z_offset=0)) -> None:
        self.config = config
        self.uuid = uuid.uuid4()
        self.plotWidget = parent.plotWidget
        self.k = 1  # 2 if geo else 1
        self.sld_id = sld_id
        
        # bus_names, bus_coords_3d = load_bus_coords_for_current_stations(config, return_3d=True, geo=geo)
        
        # bus_coords_3d[:, 1] *= self.k
        self.read_sld_data(config["database"])

        # self.x = bus_coords_3d[:, 0]
        # self.y = bus_coords_3d[:, 1]
        # self.z = bus_coords_3d[:, 2]
        self.y *= self.k
        bus_coords_3d = np.vstack([self.x, self.y, self.z]).T

        self.heatmap = HeatMapBasePlot(
            plot_window=self.plotWidget,
            coords=bus_coords_3d,
            **heatmap_kwargs
        )
        self.heatmap.im.setZValue(-10)

        # pmu_tw = PMUTimeWindowOnline(n_samples=1, kafka_topic=config['topics']['pmudata'], io_kwargs=config["streaming"])
        # pmu_tw.initialize()
        # self.pmu_tw = pmu_tw
        # pmu_tw_thread = threading.Thread(target=pmu_tw.run, daemon=True)
        # pmu_tw_thread.start()
        self.pmu_tw = SnapshotApp(
            # n_samples=1,
            input_topic=config["topics"]["pmudata"],
            io_kwargs=config["streaming"],
        )
        # self.pmu_tw.update_callbacks.append(lambda: print("Update"))

        pmu_tw_thread = threading.Thread(target=self.pmu_tw.run, daemon=True)
        pmu_tw_thread.start()

        # self.freq_col_idx = self.pmu_tw.tw.get_col_idx(measurement="f")

        self.bus_mdl = model_lib.bus.Bus(
            config["database"], self.pmu_tw.get_sample_data_frame()
        )

        parent.update_funs[self.uuid] = self.update_heatmap

    def read_sld_data(self, db_kwargs):
        all_sld = get_from_database(db_kwargs, "single_line_diagrams")
        current_sld = all_sld[all_sld["name"] == self.sld_id]["data"].values
        if len(current_sld) == 0:
            raise LayerFailedException(f"Could not read SLD data for {self.sld_id}")
        dxf_data = current_sld[-1]
        dxf_file_stream = StringIO(dxf_data)
        doc = ezdxf.read(dxf_file_stream)
        self.bus_data = get_from_database(db_kwargs, "bus")

        self.bus_names, self.bus_coords = sld.get_buses(
            doc, self.bus_data["name"].to_numpy()
        )
        self.x = self.bus_coords[:, 0]
        self.y = self.bus_coords[:, 1]
        self.z = self.y * 0

    def update_heatmap(self):
        # freq = self.pmu_tw.tw.get_col(self.freq_col_idx).flatten()
        dataframe = self.pmu_tw.most_recent_data_frame
        if dataframe is None:
            return
        freq = self.bus_mdl.freq(dataframe)
        self.heatmap.update(freq - np.mean(freq))

    def remove_layer(self):
        self.plotWidget.removeItem(self.heatmap.im)
        self.heatmap.cb.hide()
        del self.heatmap.cb


# class VoltageHeatMap(FrequencyHeatMap):
#     def __init__(self, *args, **kwargs) -> None:
#         heatmap_kwargs = dict(y_scale=1, lims=[-0.035, 0.035], z_offset=0)
#         super().__init__(heatmap_kwargs)

        # pmu_tw = PMUTimeWindow(n_samples=1, kafka_topic=config['topics']['pmudata'], io_kwargs=config["streaming"])
        # col_idx = [pmu_tw.tw.get_col_idx(station=station_name, measurement='v')[0] for station_name in pmu_tw.station_names]
        # def update_fun():
        # phasors = pmu_tw.tw.get_col(col_idx).flatten()
        # z = abs(phasors)
        # heatmap.update(z)


if __name__ == "__main__":
    from pswamp.test_utils.sample_datasets.minimal_case import create_minimal_test_case
    from pswamp.gui.grid_view.dim_2d.base_plot import GridBasePlot2D
    from nqkafka.utils import stop_server

    config, con, pmu = create_minimal_test_case()
    # print(config)
    # config["streaming"]["consumers_seek_to_beginning"] = True

    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot2D(
        # geo=False,
    )
    grid_plot.window.show()

    layer_instance = FrequencyHeatMap(grid_plot, config, sld_id="sld1")
    # layer_instance = LineLayer(grid_plot, config, geo=False)
    # layer_settings = CountriesLayerSettings(layer_instance)
    # layer_settings.show()
    # layer_instance.remove_layer()
    from pswamp.streaming import Producer
    dataframe = pmu.generate_dataframe(freq_data=[49, 51, 50])
    producer = Producer(**config["streaming"])
    producer.send(topic="pmudata", msg=dataframe)

    app.exec()
    stop_server(config["streaming"]["bootstrap_servers"])
