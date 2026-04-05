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

import pyqtgraph as pg
import numpy as np

def add_timeline_entry(ax, x, txt, color):
    infline = pg.InfiniteLine(pos=(x), movable=False, pen=pg.mkPen(width=2, color=color))
    inflabel = pg.InfLineLabel(infline, txt, position=0.9, fill=color)
    ax.addItem(infline)
    return infline

if __name__ == '__main__':

    t = np.arange(0, 10, 0.01)
    x = np.random.randn(len(t))
    x = np.cumsum(x)

    app = pg.mkQApp()
    win = pg.GraphicsLayoutWidget()
    ax = win.addPlot()
    pl = pg.PlotCurveItem(t, x)
    ax.addItem(pl)

    add_timeline_entry(ax, 0.5, 'hei', [250, 50, 50])

    add_timeline_entry(ax, 5, 'hei', [50, 250, 50])

    add_timeline_entry(ax, 12, 'hei', [50, 50, 250])


    win.show()

    app.exec()
