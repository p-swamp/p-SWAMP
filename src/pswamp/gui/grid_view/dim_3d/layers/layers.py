from PySide6 import QtGui
import numpy as np
from pswamp.visualization.components.phasor_plot_3d import PhasorPlot3D
from pswamp.visualization.components.phasor_plot_3d_fast import PhasorPlot3D as PhasorPlot3DFast
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
from pswamp.visualization.components.channel_tree import ChannelTree
import pyqtgraph.opengl as gl
import pswamp.gui.grid_view.dim_2d.layers as layers_2d
from pswamp.utils.gl import set_gl_options


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