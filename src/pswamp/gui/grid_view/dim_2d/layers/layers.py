import numpy as np
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindowOnline
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.components.phasor_plot import PhasorPlot
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations, load_bus_coords_for_stations
from pswamp.utils.single_line_diagram import load_dxf


class LayerFailedException(Exception):
    "Raised when layer fails."
    pass

class PhasorPlotLayer:
    def __init__(self, parent, config, geo=True) -> None:
        self.config = config
        self.k = 2 if geo else 1
        self.uuid = uuid.uuid4()
        self.parent = parent

        pmu_tw = PMUTimeWindowOnline(
            n_samples=1, kafka_topic=config['topics']['pmudata'], io_kwargs=config["streaming"])
        pmu_tw.initialize()
        self.pmu_tw = pmu_tw

        stations_to_plot = []

        self.col_idx_mag = []
        self.col_idx_ang = []
        for station_name in np.unique(pmu_tw.header['station']):
            idx_mag_ = pmu_tw.tw.get_col_idx(
                station=station_name.strip(), measurement='v_Magnitude')
            idx_ang_ = pmu_tw.tw.get_col_idx(
                station=station_name.strip(), measurement='v_Angle')
            if len(idx_mag_ > 0) and len(idx_mag_) == len(idx_ang_):
                # col_idx.append((idx_mag[0], idx_ang[0]))
                self.col_idx_mag.append(idx_mag_[0])
                self.col_idx_ang.append(idx_ang_[0])
                stations_to_plot.append(station_name.strip())

        # col_idx = [pmu_tw.tw.get_col_idx(station=station_name.strip(), measurement='v')[0] for station_name in pmu_tw.station_names]
        bus_coords = load_bus_coords_for_stations(config, stations_to_plot, geo=geo)
        bus_names_all, bus_coords_all = load_bus_coords_for_current_stations(config, geo=geo)
        bus_coords[:, 1] *= self.k

        pmu_tw_thread = threading.Thread(target=pmu_tw.run, daemon=True)
        pmu_tw_thread.start()
        
        self.plotWidget = parent.plotWidget
        self.phasor_plot = self.add_phasor_plot(bus_coords)

        
        # for station_name in pmu_tw.station_names:
        #     if len(pmu_tw.tw.get_col_idx(station=station_name.strip(), measurement='v')) == 0:
        #         break

        # # DEBUG
        # pmu_tw.tw.header['station'][0] == pmu_tw.station_names[0].strip()
        # pmu_tw.tw.header['measurement'][0] == 'v'
        # ix = pmu_tw.tw.get_col_idx(station=station_name.strip())
        # pmu_tw.header[ix]
        # DEBUG
        # col_idx = [pmu_tw.tw.get_col_idx(station=station_name.strip(), measurement='v')[0] for station_name in pmu_tw.station_names]
        # pmu_tw.tw.get_col_idx(
        #     station=pmu_tw.station_names[0].strip(), measurement='v')

        def phasor_fun():
            # Get the first voltage measurement at each station
            mag = pmu_tw.tw.get_col(self.col_idx_mag).flatten()
            ang = pmu_tw.tw.get_col(self.col_idx_ang).flatten()
            phasors = mag*np.exp(1j*ang)
            return phasors
        
        def update_phasors():
            phasors = phasor_fun()
            if np.all(np.isnan(phasors)):
                return
            self.phasor_plot.update(phasors)

        parent.update_funs[self.uuid] = update_phasors

    def add_phasor_plot(self, bus_coords):
        return PhasorPlot(
            self.plotWidget, pos0=bus_coords, plot_widget=self.plotWidget, normalize_angle='mean'
        )

    def remove_layer(self):
        self.pmu_tw.stop()
        for single_phasor_plot in self.phasor_plot.phasor_plots:
            self.plotWidget.removeItem(single_phasor_plot)

        del self.parent.update_funs[self.uuid]
        del self.phasor_plot


class StaticLineDataLayer:
    def __init__(self, parent, config, geo=True, data_subkey='line_data_path') -> None:
        self.config = config
        data_key = 'geo_data' if geo else 'sld_data'
        if not (data_key in config and data_subkey in config[data_key]):
            raise LayerFailedException('Line data path not found, layer could not be shown.')
        
        self.k = 2 if geo else 1
        self.parent = parent
        plotWidget = parent.plotWidget

        self.line_style = {
            'lines_lv': {
                'color': '#9CFB9C',  # (66, 227, 214),  # '#002800',
                'width': 0.01 if geo else 2
            },
            'lines_mv': {
                'color': '#42E3D6',  # (171, 253, 175),  # '  # 000064',
                'width': 0.05 if geo else 2
            },
            'lines_hv': {
                'color': '#ffae5a',  # (255, 174, 90),  # '#640000',
                'width': 2,  # 0.75 if geo else 2
            },
            }

        line_data_path = config[data_key][data_subkey]
        if line_data_path.suffix == '.npz':
            ps_geo_data_npz = np.load(line_data_path)
        elif line_data_path.suffix == '.dxf':
            ps_geo_data_npz = load_dxf(line_data_path)
            for key in ps_geo_data_npz.keys():
                ps_geo_data_npz[key][:, 1] /= self.k

        self.ps_geo_data = dict()
        i = 0
        self.power_lines_pl = dict()
        for key, in zip(
            ["lines_lv", "lines_mv", "lines_hv"],
            # [0.01, 0.05, 0.75] if geo else [2, 2, 2],
            # ["#002800", "#000064", "#640000"],
        ):

            color = self.line_style[key]['color']
            line_width = self.line_style[key]['width']

            pos = ps_geo_data_npz[key]
            i += 1
            pos[:, 1] *= self.k
            self.ps_geo_data[key] = pos

            # power_lines_pl = gl.GLLinePlotItem(
            # pos=pos, width=line_width, color=color, antialias=False
            # )
            power_lines_pl = self.add_line_plots(pos, line_width, color)
                
            plotWidget.addItem(power_lines_pl)
            self.power_lines_pl[key] = power_lines_pl

        if geo:
            self.power_lines_pl['lines_lv'].hide()
            self.power_lines_pl['lines_mv'].hide()
            

    def add_line_plots(self, pos, line_width, color):
        return pg.PlotCurveItem(
            pos[:, 0], pos[:, 1], connect='finite', pen=pg.mkPen(color=color, width=line_width))  # QtGui.QColor(color))
        

    def remove_layer(self):
        for key in ["lines_lv", "lines_mv", "lines_hv"]:
            self.parent.plotWidget.removeItem(self.power_lines_pl[key])
        # del self.geo_lines

    def show_lines(self, key):
        self.power_lines_pl[key].show()

    def hide_lines(self, key):
        self.power_lines_pl[key].hide()

    def set_power_lines_color(self, key, color):
        self.line_style[key]['color'] = color
        self.update_line_plots(key, **self.line_style[key])

        
    def set_line_width(self, key, line_width):
        self.line_style[key]['width'] = line_width
        self.update_line_plots(key, **self.line_style[key])

    def update_line_plots(self, key, **style_kwargs):
        self.power_lines_pl[key].setPen(pg.mkPen(**style_kwargs))


class StaticLineDataLayer_v0(StaticLineDataLayer):
    def __init__(self, *args, **kwargs):
        super().__init__(data_subkey='static_line_data_path', *args, **kwargs)



class StaticLineDataLayerSettings(QtWidgets.QWidget):
    def __init__(self, target_layer):
        self.target_layer = target_layer
        super().__init__()

        # self.target_layer = grid_plot

        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)
        self.btn_name_to_key = dict()
        for i, (key, name) in enumerate(
            zip(
                ["lines_lv", "lines_mv", "lines_hv"],
                ["LV", "MV", "HV"],
                # ["#002800", "#000064", "#640000"],
            )
        ):
            self.btn_name_to_key[name] = key
            button = QtWidgets.QPushButton(name)
            button.setCheckable(True)
            button.setChecked(True)
            button.clicked.connect(self.update_grid_plots)
            layout.addWidget(button, i, 0)

            color = self.target_layer.line_style[key]['color']

            # win = QtGui.QMainWindow()
            color_btn = pg.ColorButton()
            color_btn.setColor(color)

            def change(color_btn, key=key):
                self.target_layer.set_power_lines_color(key, color_btn.color())

            def done(color_btn, key=key):
                self.target_layer.set_power_lines_color(key, color_btn.color())

            color_btn.sigColorChanging.connect(change)
            color_btn.sigColorChanged.connect(done)

            line_width_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)

            def slider_change(val, key=key):
                # print(val)
                # data = self.target_layer.get_geo_data(key)
                # data[:, 2] = val / 10
                # self.target_layer.power_lines_pl[key].setData(width=val//10)
                # self.target_layer.power_lines_pl[key].setData(pos=data)
                # self.target_layer.set_power_lines_data(key, data)
                self.target_layer.set_line_width(key, val/10)

            line_width_slider.valueChanged.connect(slider_change)
            layout.addWidget(line_width_slider, i, 2)

            layout.addWidget(color_btn, i, 1)

        # i = 4
        # button = QtWidgets.QPushButton("Borders")
        # button.setCheckable(True)
        # button.setChecked(True)

        # def change_visibility(state):
        #     if state:
        #         self.target_layer.show_geo_lines()
        #     else:
        #         self.target_layer.hide_geo_lines()

        # button.clicked.connect(change_visibility)
        # layout.addWidget(button, i, 0)

        # # win = QtGui.QMainWindow()
        # color_btn = pg.ColorButton()
        # color_btn.setColor("#404040")

        # def change(color_btn, key=key):
        #     self.target_layer.set_geo_lines_color(color=color_btn.color())

        # def done(color_btn, key=key):
        #     self.target_layer.set_geo_lines_color(color=color_btn.color())

        # color_btn.sigColorChanging.connect(change)
        # color_btn.sigColorChanged.connect(done)

        # line_width_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)

        # def slider_change(val):
        # pass

        # line_width_slider.valueChanged.connect(slider_change)
        # layout.addWidget(line_width_slider, i, 2)
        # layout.addWidget(color_btn, i, 1)

        # Add bus name toggle button
        # i = 5
        # button = QtWidgets.QPushButton("Bus names")
        # button.setCheckable(True)
        # button.setChecked(True)

        # def change_bus_name_visibility(state):
        #     if state:
        #         self.target_layer.show_bus_names()
        #     else:
        #         self.target_layer.hide_bus_names()

        # button.clicked.connect(change_bus_name_visibility)
        # layout.addWidget(button, i, 0)

        self.show()

    def update_grid_plots(self, state):
        key = self.sender().text()
        if state is True:
            # power_lines_pl[self.btn_name_to_key[key]].show()
            self.target_layer.show_lines(self.btn_name_to_key[key])
        else:
            # power_lines_pl[self.btn_name_to_key[key]].hide()
            self.target_layer.hide_lines(self.btn_name_to_key[key])


