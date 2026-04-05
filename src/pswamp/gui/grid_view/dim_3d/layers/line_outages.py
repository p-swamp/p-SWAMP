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

from pswamp.gui.grid_view.dim_3d.layers.lines import LineLayer
from PySide6 import QtWidgets
import numpy as np
import threading
import uuid
from pswamp.app_templates.snapshot_app import SnapshotApp
from pswamp.models.line import Line


class LineOutages(LineLayer):
    def __init__(self, parent, config, *args, **kwargs):
        self.config = config
        self.uuid = uuid.uuid4()
        super().__init__(parent, config, *args, **kwargs)
        
        self.snapshot_app = SnapshotApp(io_kwargs=config["streaming"])
        self.line_model = Line(self.config["database"], self.snapshot_app.get_sample_data_frame())
        # n_samples = 2
        # self.pmu_tw = PMUTimeWindowOnline(n_samples=n_samples, kafka_topic=config['topics']['pmudata'], io_kwargs=config["streaming"])
        # self.pmu_tw.initialize()
        # self.col_idx, self.currents_in_measurements = self.get_col_idx()
        app_thread = threading.Thread(target=self.snapshot_app.run, daemon=True)
        app_thread.start()

        
        # self.set_colors(np.zeros(4), "trafo")
        # self.update_trafo_colors()
        
        # self.threshold = 0.01
        parent.update_funs[self.uuid] = self.update_line_outage_colors
        # self.set_trafo_colors(np.zeros((len(self.trafos_data), 4)))

    # def get_col_idx(self):
    #     i_mag_cols = self.pmu_tw.tw.get_col_idx(measurement='i_Magnitude')
    #     found_idx = []
    #     mask = []
    #     for line_name in self.lines_data['name']:
    #         string_to_be_found = line_name
    #         strings_to_search_in = np.array([h[1] for h in self.pmu_tw.tw.header[i_mag_cols]])
    #         idx = np.flatnonzero(np.core.defchararray.find(strings_to_search_in,string_to_be_found)!=-1)
    #         if len(idx) == 0:
    #             mask.append(False)
    #             continue

    #         # strings_to_search_in[idx]
    #         found_idx.append(i_mag_cols[idx[0]])
    #         mask.append(True)

    #     return np.array(found_idx), np.array(mask)
    
    # def update_z(self):
        # freq = self.pmu_tw.tw.get_col(self.col_idx).flatten()
        # z = self.z_0 + self.z_scale*(freq - 50)
        # self.set_node_z(z)
        
    def update_line_outage_colors(self):
        data_frame = self.snapshot_app.most_recent_data_frame
        if data_frame is None:
            return
        
        disconnected = self.line_model.disconnected(data_frame)
        # self.line_outage_state = np.ones(len(self.col_idx), dtype=bool)
        colors = np.zeros((len(self.model_data["line"]), 4))
        colors[disconnected] = [0.8, 0.2, 0.2, 1]

        # current_data = self.pmu_tw.tw.get_col(self.col_idx)
        # is_disconnected = np.all(current_data < self.threshold, axis=0)
        # colors_for_currents_in_measurements = colors[self.currents_in_measurements]
        # colors_for_currents_in_measurements[is_disconnected] = [0.8, 0.2, 0.2, 1]
        # colors[self.currents_in_measurements] = colors_for_currents_in_measurements
        self.set_colors(colors, "line")
        self.update_colors()

    def add_line_plots(self, pos, line_width=7, color='gray'):
        return super().add_line_plots(pos, line_width, color)



# class LinesOutagesSettings(Frequency3DLayerSettings):
    # pass
    # def slider_change(self, val):
    #     self.target_layer.z_scale = val/2

if __name__ == "__main__":
    from pswamp.test_utils.sample_datasets.minimal_case import create_minimal_test_case
    from pswamp.gui.grid_view.dim_3d.base_plot import GridBasePlot3D
    # from pswamp.gui.grid_view.dim_3d.layers.countries import CountriesLayer
    import pswamp.gui.grid_view.dim_3d.layers as lrs
    from nqkafka.utils import stop_server

    config, con, pmu = create_minimal_test_case()
    # print(config)
    # config["streaming"]["consumers_seek_to_beginning"] = True

    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot3D(
        # config,
        # sld_id="sld1"
        # geo=False,
    )
    grid_plot.window.show()

    bus_names = lrs.BusesLayer(grid_plot, config, sld_id="sld1")
    bus_names_layer = lrs.BusNamesLayer(grid_plot, config, sld_id="sld1")
    # countries_layer = CountriesLayer(grid_plot, config, sld_id="sld1")
    lines_layer = LineLayer(grid_plot, config, sld_id="sld1")
    line_outages = LineOutages(grid_plot, config, sld_id="sld1")

    # layer_instance.remove_layer()

    from pswamp.streaming import Producer
    dataframe = pmu.generate_dataframe(
        phasor_data=[
            [(1, 0), (0, 0), (1, 0)],
            [(1, 0), (0, 0), (1, 0)],
            [(1, 0), (1, 0), (1, 0)],
        ]
    )
    producer = Producer(**config["streaming"])
    producer.send(topic="pmudata", msg=dataframe)

    app.exec()
    stop_server(config["streaming"]["bootstrap_servers"])
    
# if __name__ == '__main__':
#     from pswamp.gui.grid_view.dim_3d.base_plot_layers import GridBasePlot3D
#     from pswamp import load_config

#     config = load_config()

#     app = QtWidgets.QApplication()
#     grid_plot = GridBasePlot3D()
#     grid_plot.window.show()

#     layer_instance = LineOutages(grid_plot, config, geo=False)
#     n_lines = layer_instance.n_lines

#     # layer_settings = LinesFreqSettings(layer_instance)
#     # layer_settings.show()

#     app.exec()
