# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

# from PySide6 import QtGui
import numpy as np
from pswamp.visualization.components.phasor_plot_3d import PhasorPlot3D
from pswamp.visualization.components.phasor_plot_3d_fast import PhasorPlot3D as PhasorPlot3DFast
# from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
# from pswamp.visualization.components.channel_tree import ChannelTree
# import pyqtgraph.opengl as gl
import pswamp.gui.grid_view.dim_2d.layers as layers_2d
# from pswamp.utils.gl import set_gl_options


# class StationNamesLayer(layers_2d.StationNamesLayer):
#     def add_text(self, coord, text):
#         font = QtGui.QFont()
#         font.setPixelSize(12)
#         text_item = gl.GLTextItem(
#             pos=coord, text="{}".format(text), font=font
#         )
#         set_gl_options(self.config, text_item)
#         return text_item

class PhasorPlotLayer(layers_2d.PhasorPlotLayer):
    phasor_plot_class = PhasorPlot3D
    def add_phasor_plot(self, bus_coords):
        
        bus_coords_3d = np.hstack([bus_coords, np.ones((len(bus_coords), 1))])
        phasor_plot = self.phasor_plot_class(
            self.plotWidget,
            pos0=bus_coords_3d.T,
            normalize_angle='mean'
        )

        return phasor_plot
    

class PhasorPlotFastLayer(PhasorPlotLayer):
    phasor_plot_class = PhasorPlot3DFast

    def remove_layer(self):
        self.pmu_input.stop()
        self.plotWidget.removeItem(self.phasor_plot.phasor_plot)

        del self.parent.update_funs[self.uuid]
        del self.phasor_plot


if __name__ == "__main__":
    from pswamp.test_utils.sample_datasets.minimal_case import create_minimal_test_case
    from pswamp.gui.grid_view.dim_3d.base_plot import GridBasePlot3D
    from PySide6 import QtWidgets

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
    lines_layer = lrs.LineLayer(grid_plot, config, sld_id="sld1")
    # line_outages = LineOutages(grid_plot, config, sld_id="sld1")

    phasor_layer = PhasorPlotLayer(grid_plot, config, sld_id="sld1")
    # phasor_layer_fast = PhasorPlotFastLayer(grid_plot, config, sld_id="sld1")

    # layer_instance.remove_layer()

    from pswamp.streaming import Producer

    dataframe = pmu.generate_dataframe(
        phasor_data=[
            [(1, 0), (0, 0), (1, 0)],
            [(1, 0.2), (0, 0), (1, 0)],
            [(1, 0.5), (1, 0), (1, 0)],
        ]
    )
    producer = Producer(**config["streaming"])
    producer.send(topic="pmudata", msg=dataframe)

    app.exec()
    stop_server(config["streaming"]["bootstrap_servers"])

# class StaticLineDataLayer(layers_2d.StaticLineDataLayer):
#     def add_line_plots(self, pos, line_width, color):
#         pl = gl.GLLinePlotItem(
#             pos=pos, width=line_width, color=color, antialias=False
#         )
#         set_gl_options(self.config, pl)
#         return pl


#     def remove_layer(self):
#         for key in ["lines_lv", "lines_mv", "lines_hv"]:
#             self.parent.plotWidget.removeItem(self.power_lines_pl[key])
#         # del self.geo_lines

#     def update_line_plots(self, key, **style_kwargs):
#         self.power_lines_pl[key].setData(**style_kwargs)

#     def hide(self):        
#         [self.power_lines_pl[key].hide() for key in ["lines_lv", "lines_mv", "lines_hv"]]

#     def show(self):
#         [self.power_lines_pl[key].show() for key in ["lines_lv", "lines_mv", "lines_hv"]]


# class StaticLineDataLayer_v0(StaticLineDataLayer):
#     def __init__(self, *args, **kwargs):
#         super().__init__(data_subkey='static_line_data_path', *args, **kwargs)



# class StaticLineDataLayerSettings(layers_2d.StaticLineDataLayerSettings):
#     pass
