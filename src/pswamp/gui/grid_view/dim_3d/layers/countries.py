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

import pswamp.gui.grid_view.dim_2d.layers as layers_2d
from pswamp.utils.gl import set_gl_options
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
from PySide6 import QtWidgets
import pyqtgraph.opengl as gl
import numpy as np



class CountriesLayer(layers_2d.CountriesLayer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.plotWidget.setCameraPosition(
        #     pos=QtGui.QVector3D(
        #         np.nanmean(self.geo_data[:, 0]), np.nanmean(self.geo_data[:, 1]), 0
        #     ),
        #     distance=40,
        #     elevation=12,
        #     azimuth=-90,
        # )
    
    def add_geo_lines(self, geo_data):
        geo_data = np.hstack([geo_data, np.zeros((len(geo_data), 1))])
        pl = gl.GLLinePlotItem(
            pos=geo_data, width=0.25, color="#404040", antialias=False
        )
        set_gl_options(self.config, pl)
        return pl

    def update_countries(self, countries=['Norway']):
        geo_data = read_geo_data(countries)
        geo_data[:, 1] *= self.k
        geo_data = np.hstack([geo_data, np.zeros((len(geo_data), 1))])
        # x=geo_data[:, 0], y=self.k*geo_data[:, 1])
        self.geo_lines.setData(pos=geo_data)


class CountriesLayerSettings(layers_2d.CountriesLayerSettings):
    pass



if __name__ == '__main__':
    from pswamp.gui.grid_view.dim_3d.base_plot_layers import GridBasePlot3D
    from pswamp import load_config

    config = load_config()
    
    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot3D(
        geo=True,
    )
    grid_plot.window.show()


    layer_instance = CountriesLayer(grid_plot, config, geo=True)
    layer_settings = CountriesLayerSettings(layer_instance)
    layer_settings.show()

    app.exec()
