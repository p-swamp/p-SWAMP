import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore
from pswamp import load_config
from pswamp.coordination.alarm_handling import AlarmMonitor
import numpy as np
from pswamp.visualization.time_window_plot import TimeSeriesPlot
import time
from pswamp.utils.misc import flatten_array_insert_nan
from pswamp.gui.alarms.views.default import BaseAlarmView
from pswamp.visualization.voltage_phasor_plot import VoltagePhasorPlot
from pswamp.visualization.components.phasor_plot import PhasorPlotFast, PhasorPlotFastFancy, PhasorBasePlot, xy_from_phasors
from pswamp.utils.misc import convert_time_stamp_to_seconds, flatten_array_insert_nan, convert_seconds_to_datetime
from pswamp.app_templates.snapshot_app import SnapshotApp
from pswamp.styles import colors
from pswamp.gui.grid_view.dim_3d.layers import Islanding
from pswamp.gui.grid_view.dim_3d.base_plot_layers import GridBasePlot3DLayers
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations
from pswamp.gui.grid_view.dim_3d.layers.lines import LineLayer
from pswamp.styles.colors import gl_color
from pswamp.models.line import Line
from pswamp.gui.alarms.views.default import BaseAlarmView, DefaultAlarmView






class InteractiveAlarmView(DefaultAlarmView):
    def __init__(self, *args, define_layout=True, **kwargs):

        BaseAlarmView.__init__(self, *args, **kwargs)

        self.col_idx_freq = self.tw_app.tw.get_col_idx(measurement='f')

        self.freq_ax = TimeSeriesPlot()
        pl = self.freq_ax.add_plot()

        self.pmu_data_rate = self.tw_app.get_input_data_rate()

        self.freq_ax_inf_line = pg.InfiniteLine(0)
        self.freq_ax.plotWidget.addItem(self.freq_ax_inf_line)

        self.draw_alarm_timeline_entry(self.freq_ax.plotWidget, self.alarm_data["time_stamp"], 'Alarm start')
        if self.alarm_data["time_stamp_end"] is not None: 
            self.draw_alarm_timeline_entry(self.freq_ax.plotWidget, self.alarm_data["time_stamp_end"], 'Alarm end')

        self.online = True
        self.last_slider_value = 0

        # Add slider
        self.time_slider = time_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        time_slider.setMinimum(0)
        time_slider.setMaximum(1)
        self.slider_max_range = 1
        time_slider.valueChanged.connect(lambda state: self.update_from_slider())
        time_slider.setAccessibleName('')
        time_slider.setValue(0)

        self.tw_app.update_funs.append(self.update_slider_range)

        if define_layout: self.define_layout()

    def update_slider_range(self, tw_app):
        self.slider_max_range = len(tw_app.tw.get_time()) - 1
        if self.online:
            self.time_slider.setMaximum(self.slider_max_range)
            self.time_slider.setValue(len(tw_app.tw.get_time()))


    def define_layout(self):
        layout_outer = QtWidgets.QVBoxLayout()
        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(self.freq_ax)
        layout_outer.addLayout(layout)
        layout_outer.addWidget(self.time_slider)
        self.setLayout(layout_outer)

    
    def update_from_slider(self):
        value = self.time_slider.value()
        self.last_slider_value = value
        if value == self.time_slider.maximum():
            self.time_slider.setMaximum(self.slider_max_range)
            self.freq_ax.plotWidget.getViewBox().enableAutoRange()
            # The other loop updates plots
            self.online = True
        else:
            self.freq_ax.plotWidget.getViewBox().disableAutoRange(axis=None)
            self.online = False
            self.update_plots(value)
    
    def update_function(self):
        value = self.time_slider.maximum() if self.online else self.time_slider.value()
        if self.online:
            self.update_plots(value)
            # else:
            # value = self.time_slider.value()
            
    def update_plots(self, value):
        self.freq_ax.plots[0].setData(
            *flatten_array_insert_nan(*self.tw_app.tw.get(self.col_idx_freq))
        )
        self.freq_ax_inf_line.setValue(self.tw_app.tw.get_time()[value])


if __name__ == '__main__':
    from pswamp.gui.grid_view.grid_view_container import GridViewContainer
    config = load_config()

    run_online = False
    if run_online:
        config["streaming"]['consumers_seek_to_beginning'] = True
        config["streaming"]['bootstrap_servers'] = 'localhost:40000'

        alarm_monitor = AlarmMonitor(
            io_kwargs=config["streaming"],
            alarm_topic=config['topics']['alarms'],
        )
        alarm_monitor.start()
        import time
        while True:
            try:
                alarm_uuid = list(alarm_monitor.alarm_data.keys())[-1]
                alarm_data = list(alarm_monitor.alarm_data.values())[-1]
                break
            except IndexError:
                time.sleep(1)
                pass

        config["streaming"]['consumers_seek_to_beginning'] = False
        app = QtWidgets.QApplication()

        grid_view = GridViewContainer(config, True)
        grid_view.show()

        alarm_view = InteractiveAlarmView(
            config, alarm_uuid=alarm_uuid, alarm_data=alarm_data, grid_view=grid_view)
        alarm_view.show()
        app.exec()

    else:
        config = load_config()
        # from pswamp.test_utils.mock_case import run_mock_case, stop_mock_case, KafkaProducer
        from pswamp.test_utils.sample_datasets.n44_mock_case import run_mock_case, stop_mock_case
        config["streaming"]['bootstrap_servers'] = 'localhost:50000'

        islanding_data_frames = [{
            'parameters': {'eval_freq': 1},
            'result': {
                'time_stamp': time_stamp,
                'islands': [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]] if time_stamp > 5 else []
            }
        } for time_stamp in np.arange(0, 10)]

        mock_case = run_mock_case(
            config, topic_data={'islanding': islanding_data_frames}, t_end = 10)

        alarm_data = {
            "time_stamp": convert_seconds_to_datetime(5.0),
            "time_stamp_end": convert_seconds_to_datetime(10.0),
        }
        alarm_uuid = 1

        app = QtWidgets.QApplication()

        grid_view = GridViewContainer(config, False)
        grid_view.show()

        alarm_view = InteractiveAlarmView(
            config, alarm_uuid=alarm_uuid, alarm_data=alarm_data, grid_view=grid_view)
        alarm_view.show()

        # producer = KafkaProducer(**config["streaming"])
        # [producer.send('islanding', df) for df in islanding_data_frames]

        app.exec()

        stop_mock_case(config)
