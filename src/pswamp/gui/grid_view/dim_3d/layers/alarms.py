import numpy as np
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindowOnline
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.components.phasor_plot import PhasorPlot
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations, load_bus_coords_for_stations
import pyqtgraph.opengl as gl
from pswamp.coordination.alarm_handling import AlarmMonitor


class AlarmLayer:
    def __init__(self, parent, config, geo=True) -> None:
        self.config = config

        self.plotWidget = parent.plotWidget

        self.k = 2 if geo else 1
        self.uuid = uuid.uuid4()
        self.parent = parent
        self.z_scale = 3

        bus_names, bus_coords_3d = load_bus_coords_for_current_stations(
            config, geo=geo, return_3d=True)
        bus_coords_3d[:, 1] *= self.k
        self.x = bus_coords_3d[:, 0]
        self.y = bus_coords_3d[:, 1]

        self.alarm_monitor = AlarmMonitor(
            io_kwargs=config["streaming"],
            alarm_topic=config['topics']['alarms'],
        )
        self.alarm_monitor.start()
        
        self.alert_scatter = gl.GLScatterPlotItem(
            color=[250, 250, 200],
            size=100
        )

        self.emergency_scatter = gl.GLScatterPlotItem(
            color=[250, 200, 200],
            size=100
        )
        parent.update_funs[self.uuid] = self.update_scatter

    def update_scatter(self):
        alarm_data_dict = self.alarm_keeper.alarm_data  # .copy()
        # n_alarms = len(alarm_data_dict.keys())
        
        for i_alarm, (alarm_uuid, alarm_data) in enumerate(alarm_data_dict.items()):

            for key in ['time_stamp', 'app_name', 'status']:
                item_text = str(alarm_data[key])
            # button = QtWidgets.QPushButton('Ack')
            # button.setStyleSheet("background-color : yellow")
            # def ack_button():
                # print('Ack')
            # button.clicked.connect(ack_button)
            # newitem = QtWidgets.QTableWidgetItem(button)
            # self.tableWidget.setCellWidget(row, 3, button)

            # time_stamp_sec = datetime.datetime.strptime(alarm_data['time_stamp'], '%Y-%m-%d %H:%M:%S.%f').timestamp()
            # dt = time.time() - time_stamp_sec

            if alarm_data['status'] == 'silenced':
                bg = [225, 225, 225]
            elif alarm_data['status'] == 'acknowledged':
                pass
        
        # self.alert_scatter.setData(color=)
        # self.alert_scatter.setData(pos=)
    
    def remove_layer(self):
        # self.pmu_tw.stop()
        self.plotWidget.removeItem(self.bus_lines)
        

class Frequency3DLayerSettings(QtWidgets.QWidget):
    def __init__(self, target_layer):
        self.target_layer = target_layer
        super().__init__()

        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)
        freq_scale_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        freq_scale_slider.setRange(0, 100)

        def slider_change(val):
            self.target_layer.z_scale = val/10
        
        freq_scale_slider.valueChanged.connect(slider_change)
        layout.addWidget(freq_scale_slider)
        self.show()
