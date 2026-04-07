# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

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
