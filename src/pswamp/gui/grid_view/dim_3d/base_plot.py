from PySide6 import QtWidgets
import sys
import pyqtgraph as pg
from pyqtgraph.Qt import QtGui, QtCore
import pyqtgraph.opengl as gl


class GridBasePlot3D(QtWidgets.QWidget):
    station_was_clicked = QtCore.Signal(str)
    def __init__(
        self,
        geo=True,
        live_plot=True,
        background_color=None,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.geo = geo

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
        geo=True,
    )
    grid_plot.window.show()

    app.exec()   
    return app


if __name__ == '__main__':
    main()