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

import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QHBoxLayout, QDockWidget
from PySide6.QtCore import Qt
# from PySide6.QtGui import *
from pswamp.visualization.components.label_widget import LabelWidget
from pswamp.gui.app_launcher import AppLauncher
from pswamp.gui.app_monitoring import AppStatusMonitoringWidget
from pswamp.gui.alarms.overview import AlarmOverview
from pswamp.coordination.alarm_handling import AlarmSender, AlarmMonitor
from pswamp.utils.load_config import load_config
from pswamp.visualization.freq_plot import FreqPlot
from pswamp.visualization.time_window_plot_v2 import TimeWindowPlotGUI
from pswamp.gui.grid_view.grid_view_container import GridViewContainer


class CoordinationModuleGUI(QMainWindow):
    def __init__(self, config, geo_plot_kwargs={}, parent=None, activate_default_layers=True):
        super(CoordinationModuleGUI, self).__init__(parent)

        self.update_freq = 25
        self.config = config

        layout = QHBoxLayout()
        self.grid_view = GridViewContainer(config, activate_default_layers=activate_default_layers)

        # self.time_series_plot_popup = None
        # self.grid_plot.grid_plot_2d.station_was_clicked.connect(self.show_time_series_plot_popup)

        # alarm_sender = AlarmSender(
        #     io_kwargs=config["streaming"],
        #     input_topic=config['topics']['application.status'],
        #     alarm_topic=config['topics']['alarms'],
        # )
        # alarm_sender.start()

        alarm_monitor = AlarmMonitor(
            io_kwargs=config['streaming'],
            alarm_topic=config['topics']['alarms'],
        )
        alarm_monitor.start()

        if 'other_tso' in config.keys():
            alarm_monitors_other_tsos = []
            for config_ in config['other_tso']:
                alarm_monitor_other_tso = AlarmMonitor(
                    io_kwargs=config_['streaming'],
                    alarm_topic=config_['topics']['alarms'],
                )
                alarm_monitor_other_tso.start()
                alarm_monitors_other_tsos.append(alarm_monitor_other_tso)

        self.setCentralWidget(self.grid_view)

        dock_widget_area = Qt.RightDockWidgetArea
        
        if 'misc' in config and 'logo_path' in config['misc'].keys():
            self.d0 = QDockWidget("", self)
            img_path = config['misc']['logo_path'].resolve()
            self.logo_widget = LabelWidget(img_path)
            self.d0.setWidget(self.logo_widget)
            self.addDockWidget(dock_widget_area, self.d0)

        self.d1 = QDockWidget("Apps", self)
        self.launcher = AppLauncher(config)
        self.d1.setWidget(self.launcher)
        self.addDockWidget(dock_widget_area, self.d1)

        self.d110 = QDockWidget("Frequency", self)
        self.freq_plot = FreqPlot(config)
        # self.freq_plot.start()
        self.d110.setWidget(self.freq_plot)
        self.addDockWidget(dock_widget_area, self.d110)
        
        self.d11 = QDockWidget("Status", self)
        self.app_monitoring = AppStatusMonitoringWidget(config)
        self.app_monitoring.start()
        self.d11.setWidget(self.app_monitoring)
        self.addDockWidget(dock_widget_area, self.d11)

        # Dock area for alarms
        self.d_alarm = QDockWidget("Alarms", self)
        self.addDockWidget(dock_widget_area, self.d_alarm)

        self.d_alarm_focus = QDockWidget("Alarm details", self)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.d_alarm_focus)

        self.alarm_display = AlarmOverview(
            config,
            alarm_monitor,
            alarm_details_dock=self.d_alarm_focus,
            grid_view=self.grid_view,
        )

        # self.alarm_display.start()
        self.d_alarm.setWidget(self.alarm_display)
        

        if 'other_tso' in config.keys():
            self.d_alarm1 = []
            self.alarm_displays_other_tsos = []
            for config_, alarm_monitor_ in zip(config['other_tso'], alarm_monitors_other_tsos):
                new_dock_widget = QDockWidget(
                    f"Alarms {config_['name']}", self)
                alarm_display_other_tso = AlarmOverview(
                    config_,
                    alarm_monitor_,
                    # measurement_data_available=False
                    alarm_details_dock=self.d_alarm_focus,
                    grid_view=self.grid_view,
                )
                new_dock_widget.setWidget(alarm_display_other_tso)
                self.alarm_displays_other_tsos.append(alarm_display_other_tso)
                self.tabifyDockWidget(self.d_alarm, new_dock_widget)
                self.d_alarm1.append(new_dock_widget)

            self.d_alarm.raise_()

        self.setLayout(layout)
        self.setWindowTitle("pswamp")

    def show_time_series_plot_popup(self, station):
        return
        if self.time_series_plot_popup is None:
            self.time_series_plot_popup = TimeWindowPlotGUI(
                kafka_topic=self.config['topics']['pmudata'],
                kafka_topic_pmu_coords=self.config['topics']['pmu.coords'],
                io_kwargs=self.config["streaming"],
                countries=self.config['geo_data']['countries'],
                update_freq=self.update_freq,
                n_max_plots=50,
                include_map=False,
            )
            self.time_series_plot_popup.show()
            self.time_series_plot_dock = QDockWidget("Time Series Plot", self)
            self.time_series_plot_dock.setWidget(self.time_series_plot_popup)
            self.addDockWidget(Qt.RightDockWidgetArea,
                               self.time_series_plot_dock)

        # self.time_series_plot_popup.setWindowState(self.time_series_plot_popup.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        # this will activate the window
        # self.time_series_plot_popup.activateWindow()
        self.time_series_plot_popup.channel_select.filter_edit.setText(station)


def run_main_window(*config_args, activate_default_layers=True):
    config = load_config(*config_args)
    # bus_names, bus_coords = load_bus_coords_for_current_stations(config)

    app = QApplication(sys.argv)
    viz = CoordinationModuleGUI(
        config,
        activate_default_layers=activate_default_layers,
    )

    viz.showMaximized()
    app.exec()

    return app


if __name__ == '__main__':
    config = load_config()
    # config["streaming"]['consumers_seek_to_beginning'] = True
    run_main_window(config, activate_default_layers=False)
