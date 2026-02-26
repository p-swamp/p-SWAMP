from PySide6 import QtWidgets, QtCore
from pswamp import load_config
from pswamp.coordination.alarm_handling import AlarmMonitor
from pswamp.app_templates.time_window_app import TimeWindowApp
import numpy as np
from pswamp.visualization.time_window_plot import TimeSeriesPlot
from pswamp.utils.misc import convert_datetime_to_seconds, flatten_array_insert_nan, convert_seconds_to_datetime
import threading
import datetime
from pswamp.streaming import consumer_seek_relative_offset
import time
from pswamp.visualization.components.timeline import add_timeline_entry


class TimeWindowAppMod(TimeWindowApp):
    """Modified TimeWindowApp, for customizing how often updating happens.
    TODO: Generalize original TimeWindowApp so that this subclass is not needed."""
    def __init__(self, *args, store_dataframes=True, **kwargs):
        self.store_dataframes = store_dataframes
        super().__init__(*args, **kwargs)
        self.update_funs = []
        self.k = 0
        self.data_frame_storage = []

    def run_analysis(self, time_stamp, measurements):
        if time_stamp[-1] < self.time_stamp_at_init and time_stamp[-1] < self.t_end - 1:
            self.k += 1
            if not self.k % 100 == 0:
                return
        for fun in self.update_funs:
            fun(self)
        return True

    def update_storage(self, next_data_frame):
        """Update internal storage with data frames"""
        super().update_storage(next_data_frame)
        if self.store_dataframes:
            self.data_frame_storage.append(next_data_frame)
        
        # self.pmu_tw.update_window(next_data_frame)


class BaseAlarmView(QtWidgets.QWidget):
    update_requested = QtCore.Signal()

    def __init__(self, config, alarm_uuid, alarm_data, update_freq=50, grid_view=None, channel_selection=None):
        super().__init__()
        self.alarm_topic = config['topics']['alarms']
        self.grid_view = grid_view

        self.setWindowTitle('Alarm')
        self.alarm_uuid = alarm_uuid
        self.alarm_data = alarm_data

        if isinstance(self.alarm_data["time_stamp"], datetime.datetime):
            self.time_stamp_start = time_stamp_start = self.alarm_data["time_stamp"] - datetime.timedelta(seconds=5)
        else:
            self.time_stamp_start = time_stamp_start = self.alarm_data["time_stamp"] - 10
        self.time_stamp_end = time_stamp_end = self.alarm_data["time_stamp_end"]

        if time_stamp_end is not None:
            if isinstance(time_stamp_end, datetime.datetime):
                t_end_seconds = convert_datetime_to_seconds(time_stamp_end) + 10
            else:
                t_end_seconds = time_stamp_end + 10
        else:
            t_end_seconds = np.inf

        self.t_end_seconds = t_end_seconds

        self.simplified_alarm_views = config['misc']['simplified_alarm_views'] if 'misc' in config and 'simplified_alarm_views' in config['misc'] else False

        if self.simplified_alarm_views: update_freq = 5

        self.tw_app = TimeWindowAppMod(
            io_kwargs=config["streaming"],
            input_topic=config['topics']['pmudata'],
            t_start=time_stamp_start,
            t_end=t_end_seconds,
            decoder_kwargs={"channel_selection": channel_selection},  # {'measurement': 'f'},
            window_length=None,
            n_samples=None,
            auto_adjust_offset=False,
            eval_freq=update_freq,
            store_dataframes=~self.simplified_alarm_views,
        )

        if time_stamp_end is None:
            self.check_for_alarm_not_critical_thread = threading.Thread(target=self.check_for_alarm_not_critical)
            self.check_for_alarm_not_critical_thread.start()
        
        self.tw_app.update_funs.append(lambda args: self.update_requested.emit())

        self.freq_tw_thread = threading.Thread(target=self.tw_app.run, daemon=True)
        self.freq_tw_thread.start()

        self.update_requested.connect(self.update_function)
        

    def check_for_alarm_not_critical(self):
        while True:
            if self.alarm_data["time_stamp_end"] is not None:
                self.tw_app.t_end = convert_datetime_to_seconds(
                    self.alarm_data["time_stamp_end"]) + 10
                # self.freq_tw.stop()
                print('Defined stop time for alarm view.')
                self.alarm_not_critical_detected_callback()
                break
            time.sleep(1)

    def alarm_not_critical_detected_callback(self):
        pass


class DefaultAlarmView(BaseAlarmView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.col_idx_freq = self.tw_app.tw.get_col_idx(measurement='f')

        self.freq_ax = TimeSeriesPlot()
        pl = self.freq_ax.add_plot()

        self.draw_alarm_timeline_entry(self.freq_ax.plotWidget, self.alarm_data["time_stamp"], 'Alarm start')
        if self.alarm_data["time_stamp_end"] is not None: 
            self.draw_alarm_timeline_entry(self.freq_ax.plotWidget, self.alarm_data["time_stamp_end"], 'Alarm end')

        self.define_layout()

    def draw_alarm_timeline_entry(self, plotWidget, time_stamp, entry):
        if isinstance(time_stamp, datetime.datetime): time_stamp = convert_datetime_to_seconds(time_stamp)
        self.time_line_entries = {entry: add_timeline_entry(plotWidget, time_stamp, entry, [250, 50, 50])}

    def alarm_not_critical_detected_callback(self):
        self.draw_alarm_timeline_entry(self.freq_ax.plotWidget, self.alarm_data["time_stamp_end"], 'Alarm end')       


    def define_layout(self):
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.freq_ax)
        self.setLayout(layout)

    def update_function(self):
        self.update_plots(None)
    
    def update_plots(self, value):
        self.freq_ax.plots[0].setData(
            *flatten_array_insert_nan(*self.tw_app.tw.get(self.col_idx_freq))
        )

    def close_view(self):
        pass


if __name__ == '__main__':
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

        alarm_view = DefaultAlarmView(config, alarm_uuid=alarm_uuid, alarm_data=alarm_data)
        alarm_view.show()
        app.exec()

    else:
        from pswamp.test_utils.sample_datasets.n44_mock_case import run_mock_case, stop_mock_case, Producer
        config["streaming"]['bootstrap_servers'] = 'localhost:50000'
        # config["streaming"]['consumers_seek_to_beginning'] = True

        mock_case = run_mock_case(config, t_end=50)

        # time.sleep(2)
        alarm_data = {
            "time_stamp": 15.0,
            "time_stamp_end": 25.0,
        }
        alarm_uuid = 1

        app = QtWidgets.QApplication()

        alarm_view = DefaultAlarmView(
            config, alarm_uuid=alarm_uuid, alarm_data=alarm_data, grid_view=None)
        alarm_view.show()

        app.exec()

        stop_mock_case(config)
