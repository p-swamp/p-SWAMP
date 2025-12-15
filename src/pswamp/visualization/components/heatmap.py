import numpy as np
from scipy.interpolate import griddata, Rbf
import time
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore, QtGui
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data


class HeatMap:
    def __init__(self, coords, lims=[0.9, 1.1], y_scale=1, z_offset=1, background_color=(30, 63, 64), plot_window=None) -> None:
        nx = 200
        ny = 200

        self.z_offset = z_offset
        self.y_scale = y_scale

        self.not_nan_xy = ~np.any(np.isnan(coords), axis=1)

        x_in = coords[self.not_nan_xy, 0]
        y_in = coords[self.not_nan_xy, 1]*self.y_scale

        x_min = min(x_in)
        x_max = max(x_in)
        y_min = min(y_in)
        y_max = max(y_in)
        dx = x_max - x_min
        dy = y_max - y_min
        self.x = np.concatenate([x_in, [x_min - dx*0.2, x_min - dx*0.2, x_max + dx*0.2, x_max + dx*0.2]])
        self.y = np.concatenate([y_in, [y_min - dx*0.2, y_max + dx*0.2, y_min - dx*0.2, y_max + dx*0.2]])
        self.im_width = max(self.x) - min(self.x)
        self.im_height = max(self.y) - min(self.y)

        xv = np.linspace(np.min(self.x), np.max(self.x), nx)
        yv = np.linspace(np.min(self.y), np.max(self.y), ny)
        [self.X, self.Y] = np.meshgrid(xv, yv)

        im = pg.ImageItem()
        im.setImage(np.mean(lims)*np.ones_like(self.X))
        im.setRect(min(self.x), min(self.y), self.im_width, self.im_height)

        self.z_scale = 1e3  # Higher values work better with the color bar range selection

        cm = pg.ColorMap(None, [
            QtGui.QColor(255, 0, 0),
            QtGui.QColor(*background_color),
            QtGui.QColor(0, 0, 255),
        ])
        
        if plot_window is None:
            pl = pg.plot()
            pl.setBackground(background_color)
            pl.setAspectLocked(True)            #
            # pl.setMouseEnabled( x=False, y=False)
            pl.disableAutoRange()
            pl.hideButtons()
            pl.setRange(
                xRange=(min(self.x), max(self.x)),
                yRange=(min(self.y), max(self.y)),
                padding=0
            )
            pl.showAxes(False)  # , showValues=(True,False,False,True) )
            pl.show()
        else:
            pl = plot_window

        self.cb = pl.addColorBar(im, colorMap=cm, values=self.z_scale*np.array(lims))  # , interactive=False)
        # cb.hide()
        
        pl.addItem(im)


        self.im = im
        self.pl = pl
        self.interp_method = 'linear'

    def update(self, new_z):
        self.z = np.concatenate([new_z[self.not_nan_xy], self.z_offset*np.ones(4)])
        self.Z = griddata((self.x, self.y), self.z,(self.X, self.Y), method=self.interp_method)
        
        # rbf = Rbf(self.x, self.y, self.z, epsilon=0.01)
        # self.ZI = rbf(self.X, self.Y)
        self.im.setImage(self.Z.T*self.z_scale, autoLevels=False)


class HeatMapGeo(HeatMap):
    def __init__(self, *args, countries=None, **kwargs):
        super().__init__(*args, **kwargs)

        scatter_plot = pg.ScatterPlotItem(self.x[:-4], self.y[:-4])
        self.pl.addItem(scatter_plot)

        geo_data = read_geo_data(countries)
        geo_data[:, 1] *= self.y_scale
        self.geo_lines = pg.PlotCurveItem(pen=QtGui.QColor('gray'))
        self.geo_lines.setData(geo_data[:, 0], geo_data[:, 1], connect='finite')
            # geo_data, width=0.25, color="#404040", antialias=False
        # )
        self.pl.addItem(self.geo_lines)


def main():
    import sys
    sys.path.append(r'C:\Users\hallvarh\Coding\pswamp\pswamp\examples\recorded_pmu_data\data')
    import load_pmu_coordinates

    names, coords = load_pmu_coordinates.load()
    y_scale = 1/np.cos(60/180*np.pi)

    app = QtWidgets.QApplication(sys.argv)
    pl = pg.plot()
    hm = HeatMap(coords, y_scale=y_scale, plot_window=pl)
    hm_geo = HeatMapGeo(coords, y_scale=y_scale, countries=["Norway", "Sweden", "Denmark", "Finland"])

    def update_fun():

        z = np.ones(len(coords))
        z[4] = 1 + -np.sin(2*time.time())*0.1
        z[5] = 1 + np.sin(2*time.time())*0.05

        hm.update(z)
        hm_geo.update(z)

    
    update_freq = 25
    timer = QtCore.QTimer()
    timer.timeout.connect(update_fun)
    timer.start(update_freq)

    app.exec()

if __name__ == '__main__':
    main()