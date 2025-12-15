# from pswamp_viz.utils.pmu_time_window import PMUTimeWindow
# from pswamp_viz.utils.pmu_receiver import PMUReceiver
# from pswamp_viz.utils.definitions import pswamp_PATH
# from pswamp_viz.visualizations.components.phasor_plot_3d import PhasorPlot3D
# from pswamp.visualization.components.phasor_plot_3d import PhasorPlot3D
from pswamp.visualization.components.phasor_plot import PhasorPlot
import threading
import multiprocessing as mp
from PySide6 import QtWidgets
import sys
import pyqtgraph as pg
from pyqtgraph.Qt import QtGui, QtCore
import pyqtgraph.opengl as gl
import time
import shapefile
import numpy as np
import pathlib
import os
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data


class GeoPlot2D(QtWidgets.QWidget):
    station_was_clicked = QtCore.Signal(str)
    def __init__(
        self,
        update_freq=50,
        k=1,
        countries=None,
        power_line_geo_data=None,
        bus_kwargs=None,
        phasors_kwargs=None,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.k = k
        self.update_funs = []

        self.window = pg.GraphicsLayoutWidget(show=True, title="GeoPlot2D")
        self.plotWidget = self.window.addPlot()
        self.plotWidget.setAspectLocked(True)
        self.plotWidget.showAxes(False)
        self.window.setBackground((30, 63, 64))

        if countries is not None and len(countries) > 0:
            self.draw_countries(countries)
        if power_line_geo_data is not None:
            self.draw_power_line_geo_data(power_line_geo_data)
        if bus_kwargs is not None:
            self.draw_buses(**bus_kwargs)
        if phasors_kwargs is not None:
            self.draw_phasors(**phasors_kwargs)

        # self.window.show()

        if len(self.update_funs) > 0:
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self.update)
            self.timer.start(1000 // update_freq)
        self.t_prev = time.time()

    def update(self):
        for update_fun in self.update_funs:
            update_fun()

    def draw_buses(self, bus_coords, bus_names, use_colors=False):

        if bus_coords.shape[1] == 2:
            bus_coords_3d = np.hstack([bus_coords, np.ones((len(bus_coords), 1))])
        else:  # bus_coords.shape[1] == 3:
            bus_coords_3d = bus_coords.copy()

        bus_coords_3d[:, 1] *= self.k

        self.x = bus_coords_3d[:, 0]
        self.y = bus_coords_3d[:, 1]
        self.z = bus_coords_3d[:, 2]

        self.colors = lambda i: pg.intColor(
            i,
            hues=9,
            values=1,
            maxValue=255,
            minValue=150,
            maxHue=360,
            minHue=0,
            sat=255,
            alpha=255,
        )

        color = np.ones((len(bus_coords_3d), 4))
        color[:, -1] = 0.5
        if use_colors:
            color = (
                np.array([self.colors(i).getRgb() for i in range(len(bus_coords_3d))])
                / 255
            )

        font = QtGui.QFont()
        font.setPixelSize(12)
        if bus_names is not None:
            self.bus_name_text = []
            for coord, bus_name in zip(bus_coords_3d, bus_names):
                # print(coord.shape)
                # pg.TextItem
                txtitem1 = pg.TextItem(  # gl.GLTextItem(
                    anchor=(0, 0), text="{}".format(bus_name), #font=font
                )
                txtitem1.setPos(coord[0], coord[1])
                self.bus_name_text.append(txtitem1)
                self.plotWidget.addItem(txtitem1)

        self.bus_scatter = pg.ScatterPlotItem(x=bus_coords[:, 0], y=self.k*bus_coords[:, 1], brush=pg.mkBrush('white'))  # pen=pg.mkPen('w'), )

        def bus_clicked_fun(self, points, ev, bus_coords=bus_coords, bus_names=bus_names, signal=self.station_was_clicked):
            # print(points, ev)
            # print(points[0].pos())

            coord = np.array(points[0].pos())
            coord[1] /= 2
            # bus_coords
            # bus_coords = np.array([[10, 60], [11, 61], [12, 52]])
            
            bus_idx = np.argmin(np.linalg.norm(coord - np.nan_to_num(bus_coords)[:, :2], axis=1))
            # print(f'Bus number {bus_idx} was clicked, with name {bus_names[bus_idx]}')
            # return bus_names[bus_idx]
            signal.emit(bus_names[bus_idx])
                
                
        self.bus_scatter.sigClicked.connect(bus_clicked_fun)
        self.plotWidget.addItem(self.bus_scatter)

        # bus_lines_x = np.vstack([self.x] * 2 + [np.nan * np.ones(len(self.x))]).T
        # bus_lines_y = np.vstack([self.y] * 2 + [np.nan * np.ones(len(self.x))]).T
        # bus_lines_z = np.vstack([self.z, self.z * 0, np.nan * np.ones(len(self.x))]).T

        # edge_pos = np.vstack(
            # [bus_lines_x.flatten(), bus_lines_y.flatten(), bus_lines_z.flatten()]
        # ).T

        # self.bus_lines = gl.GLLinePlotItem(pos=edge_pos, antialias=True, width=0.25)
        # self.focus_scatter = gl.GLScatterPlotItem(pos=bus_coords_3d)

        # self.color = np.zeros((len(self.x), 4))
        # self.color[:, 0] = 255
        # self.focus_scatter = pg.ScatterPlotItem(  # gl.GLScatterPlotItem(
        #     pos=np.vstack([self.x, self.y]).T,  # , self.z]).T,
        #     color=self.color,
        #     size=100
        # )

        # self.focus_scatter_coords = pg.ScatterPlotItem(  # gl.GLScatterPlotItem(
        #     size=100
        # )

        # self.window.addItem(self.bus_lines)
        # self.plotWidget.addItem(self.focus_scatter)
        # self.plotWidget.addItem(self.focus_scatter_coords)

    def show_lines(self, key):
        self.power_lines_pl[key].show()

    def hide_lines(self, key):
        self.power_lines_pl[key].hide()

    def show_geo_lines(self):
        self.geo_lines.show()

    def hide_geo_lines(self):
        self.geo_lines.hide()

    def set_geo_lines_color(self, color):
        self.geo_lines.setPen(QtGui.QColor(color))  # setData(color=color)

    def set_power_lines_data(self, key, data):
        pass

    def get_geo_data(self, key):
        return self.ps_geo_data[key]
    
    def set_power_lines_color(self, key, color):
        self.power_lines_pl[key].setPen(QtGui.QColor(color))  # setData(color=color)
    
    def hide_bus_names(self):
        for text in self.bus_name_text:
            text.hide()
    
    def show_bus_names(self):
        for text in self.bus_name_text:
            text.show()
    
    def draw_bus_connectors(self):
        pass

    def draw_power_line_geo_data(self, ps_geo_data_path):
        # print(ps_geo_data_path)

        ps_geo_data_npz = np.load(ps_geo_data_path)
        self.ps_geo_data = dict()
        i = 0
        self.power_lines_pl = dict()
        for key, line_width, color in zip(
            ["lines_lv", "lines_mv", "lines_hv"],
            [0.01, 0.05, 0.75],
            ["#002800", "#000064", "#640000"],
        ):
            # if key == 'lines_lv':
            #     continue

            pos = ps_geo_data_npz[key]
            i += 1
            pos[:, 1] *= self.k
            self.ps_geo_data[key] = pos

            # power_lines_pl = gl.GLLinePlotItem(
                # pos=pos, width=line_width, color=color, antialias=False
            # )
            power_lines_pl = pg.PlotCurveItem(pos[:, 0], pos[:, 1], connect='finite', pen=QtGui.QColor(color))
            self.plotWidget.addItem(power_lines_pl)
            self.power_lines_pl[key] = power_lines_pl

    def draw_countries(self, countries):
        geo_data = read_geo_data(countries)
        geo_data[:, 1] *= self.k
        # self.window.setCameraPosition(
        #     pos=QtGui.QVector3D(
        #         np.nanmean(geo_data[:, 0]), np.nanmean(geo_data[:, 1]), 0
        #     ),
        #     distance=40,
        #     elevation=12,
        #     azimuth=-90,
        # )
        # self.geo_lines = gl.GLLinePlotItem(
        #     pos=geo_data, width=0.25, color="#404040", antialias=False
        # )
        # self.window.addItem(self.geo_lines)
        self.geo_lines = pg.PlotCurveItem(geo_data[:, 0], geo_data[:, 1], connect='finite', pen=QtGui.QColor('gray'))
        # self.geo_lines.setData(geo_data[:, 0], geo_data[:, 1], connect='finite')
            # geo_data, width=0.25, color="#404040", antialias=False
        # )
        self.plotWidget.addItem(self.geo_lines)

    def draw_phasors(self, bus_coords, phasor_fun=None):
        bus_coords = bus_coords.copy()
        bus_coords[:, 1] *= self.k

        # self.phasor_plot = PhasorPlot3D(self.window, pos0=bus_coords_3d.T)
        self.phasor_plot = PhasorPlot(self.plotWidget, pos0=bus_coords, plot_widget=self.plotWidget, normalize_angle='mean')

        if phasor_fun is not None:

            def update_phasors():
                phasors = phasor_fun()
                self.phasor_plot.update(phasors)

            self.update_funs.append(update_phasors)

    def set_focus(self, station_idx, coeffs=None):
        # pass
        # pos = np.vstack(
        #     [self.x, self.y, self.z]
        # ).T
        if coeffs is None:
            coeffs = np.ones_like(station_idx)
        else:
            coeffs = np.array(coeffs)
        new_colors = np.zeros((len(station_idx), 3))
        new_colors[coeffs > 0] = [0, 0, 255]
        new_colors[coeffs < 0] = [255, 0, 0]
        
        self.color *= 0
        self.color[station_idx, :-1] = new_colors
        self.color[station_idx, 3] = 0.5*np.array(abs(coeffs))
        self.focus_scatter.setData(color=self.color)

    def set_focus_coords(self, coords, coeffs=None):
        coords = np.array(coords)
        n_scatter = coords.shape[0]
        if coords.shape[1] == 2:
            np.hstack([coords, np.ones((n_scatter, 1))])
        
        if coeffs is None:
            coeffs = np.ones_like(n_scatter)
        else:
            coeffs = np.array(coeffs)
        
        color = np.zeros((n_scatter, 4))
        color[coeffs > 0, :-1] = [0, 0, 255]
        color[coeffs < 0, :-1] = [255, 0, 0]
        color[:, 3] = 0.5*np.array(abs(coeffs))
        self.focus_scatter_coords.setData(
            pos=coords,
            color=color
        )


class GridPlotControl(QtWidgets.QWidget):
    def __init__(self, grid_plot):
        super().__init__()

        self.grid_plot = grid_plot

        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)
        self.btn_name_to_key = dict()
        for i, (key, name, color) in enumerate(
            zip(
                ["lines_lv", "lines_mv", "lines_hv"],
                ["LV", "MV", "HV"],
                ["#002800", "#000064", "#640000"],
            )
        ):
            self.btn_name_to_key[name] = key
            button = QtWidgets.QPushButton(name)
            button.setCheckable(True)
            button.setChecked(True)
            button.clicked.connect(self.update_grid_plots)
            layout.addWidget(button, i, 0)

            # win = QtGui.QMainWindow()
            color_btn = pg.ColorButton()
            color_btn.setColor(color)

            def change(color_btn, key=key):
                self.grid_plot.power_lines_pl[key].setData(color=color_btn.color())

            def done(color_btn, key=key):
                self.grid_plot.power_lines_pl[key].setData(color=color_btn.color())

            color_btn.sigColorChanging.connect(change)
            color_btn.sigColorChanged.connect(done)

            line_width_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)

            def slider_change(val, key=key):
                # print(val)
                data = self.grid_plot.ps_geo_data[key]
                data[:, 2] = val / 10
                # self.grid_plot.power_lines_pl[key].setData(width=val//10)
                self.grid_plot.power_lines_pl[key].setData(pos=data)

            line_width_slider.valueChanged.connect(slider_change)
            layout.addWidget(line_width_slider, i, 2)

            layout.addWidget(color_btn, i, 1)

        i = 4
        button = QtWidgets.QPushButton("Borders")
        button.setCheckable(True)
        button.setChecked(True)

        def change_visibility(state):
            if state:
                self.grid_plot.geo_lines.show()
            else:
                self.grid_plot.geo_lines.hide()

        button.clicked.connect(change_visibility)
        layout.addWidget(button, i, 0)



        # win = QtGui.QMainWindow()
        color_btn = pg.ColorButton()
        color_btn.setColor("#404040")

        def change(color_btn, key=key):
            self.grid_plot.geo_lines.setData(color=color_btn.color())

        def done(color_btn, key=key):
            self.grid_plot.geo_lines.setData(color=color_btn.color())

        color_btn.sigColorChanging.connect(change)
        color_btn.sigColorChanged.connect(done)

        # line_width_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)

        # def slider_change(val):
            # pass

        # line_width_slider.valueChanged.connect(slider_change)
        # layout.addWidget(line_width_slider, i, 2)
        layout.addWidget(color_btn, i, 1)

        # Add bus name toggle button
        i = 5
        button = QtWidgets.QPushButton("Bus names")
        button.setCheckable(True)
        button.setChecked(True)

        def change_bus_name_visibility(state):
            if state:
                self.grid_plot.show_bus_names()
            else:
                self.grid_plot.hide_bus_names()

        button.clicked.connect(change_bus_name_visibility)
        layout.addWidget(button, i, 0)

        self.show()

    def update_grid_plots(self, state):
        key = self.sender().text()
        if state is True:
            self.grid_plot.power_lines_pl[self.btn_name_to_key[key]].show()
        else:
            self.grid_plot.power_lines_pl[self.btn_name_to_key[key]].hide()


def main():
    import pathlib
    pmu_data_example_folder = pathlib.Path(
        __file__).parent.parent.parent.parent.parent/'examples'/'recorded_pmu_data'/'data'
    sys.path.append(str(pmu_data_example_folder))
    import load_pmu_coordinates
    bus_names, bus_coords = load_pmu_coordinates.load()
    bus_coords_3d = np.hstack([bus_coords, np.ones((len(bus_coords), 1))])

    app = QtWidgets.QApplication(sys.argv)

    # import pathlib
    # geo_data_file_path = r'C:\Users\hallvarh\Coding\pswamp\pswamp\examples\recorded_pmu_data'
    # power_line_geo_data = pathlib.Path(geo_data_file_path) / "data" / "power_system_data" / "openinframap" / "scandinavia" / "numpy_data.npz"
    

    grid_plot = GeoPlot2D(
        update_freq=25,
        k=2,
        countries=['Norway'],
        # power_line_geo_data=power_line_geo_data,  # config['geo_data']['line_data_path'],
        bus_kwargs=dict(
            bus_coords=bus_coords,
            bus_names=bus_names,
        ),
        phasors_kwargs=dict(
            bus_coords=bus_coords_3d,
            # phasor_fun=lambda: np.random.randn(len(bus_names)) + 1j*np.random.randn(len(bus_names)),
        ),
    )
    grid_plot.window.show()

    # def update_focus():
    #     t_0 = time.time()
    #     while True:
    #         grid_plot.set_focus_coords([[16, 65], [17, 60]], [0.5, 1*np.sin(time.time())])
    #         if time.time() - t_0 < 5:
    #             grid_plot.set_focus([2, 3, 5], [1, -0.8, 0.5*np.sin(2*time.time())])
    #         else:
    #             grid_plot.set_focus([], [])
    #         time.sleep(0.1)

    # update_thread = threading.Thread(target=update_focus)
    # update_thread.start()

    
    app.exec()   
    return app


if __name__ == '__main__':
    main()