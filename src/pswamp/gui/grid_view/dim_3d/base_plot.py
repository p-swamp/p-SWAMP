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

from PySide6 import QtWidgets
import sys
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore
import pyqtgraph.opengl as gl


class GridBasePlot3D(QtWidgets.QWidget):
    station_was_clicked = QtCore.Signal(str)
    def __init__(
        self,
        live_plot=True,
        background_color=None,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)

        # self.window = pg.GraphicsLayoutWidget(show=True, title="GeoPlot2D")
            # self.plotWidget = self.window.addPlot()
        # self.plotWidget.setAspectLocked(True)
        # self.plotWidget.showAxes(False)
        
        self.window = gl.GLViewWidget()
        # pg.setConfigOption('foreground', 'k')
        # pg.setConfigOption('background', 'w')
        # pg.setConfigOption('foreground', 'k')
        self.window.setBackgroundColor(background_color if background_color else (30, 63, 64))


        self.window.setWindowTitle("Grid")
        self.plotWidget = self.window  # Compatible with 2D variant
        self.update_funs = {}

        if live_plot:
            self.start_plot_update_timer()


    def start_plot_update_timer(self, update_freq=50):
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(1000 // update_freq)


    def update(self):
        for update_fun in self.update_funs.values():
            update_fun()

    def change_background_color(self, color):
        self.window.setBackgroundColor(color)



def main():
    app = QtWidgets.QApplication(sys.argv)

    grid_plot = GridBasePlot3D(
        # update_freq=25,
    )
    grid_plot.window.show()

    app.exec()   
    return app


if __name__ == '__main__':
    main()
