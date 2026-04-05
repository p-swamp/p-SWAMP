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

import threading
# import ctypes
import sys
from PySide6 import QtWidgets, QtCore
from pswamp.visualization.components.surface_plot import SurfacePlot
from pswamp.visualization.components.channel_select import ChannelSelect
from pswamp.monitoring.fft import FFTOnline
# from pswamp.visualization.time_window_plot import TimeWindowPlot
import pyqtgraph as pg
# from qtrangeslider import QRangeSlider
from pswamp.utils.load_config import load_config
from pswamp.app_templates.time_window_app import TimeWindowApp
import numpy as np
from scipy.fft import fft, fftfreq
import time
from pswamp.utils.time_window import TimeWindow
from pswamp.utils.pmu_time_window import PMUTimeWindow
from PySide6.QtWidgets import *
from pswamp.gui.components.channel_select import ChannelSelect
import multiprocessing as mp
from pswamp.streaming import get_last_message_from_topic, consumer_seek_relative_offset
import time
from pswamp.monitoring.fft import calculate_fft_spectrum



class FFTOnlineSingleChannel(TimeWindowApp):
    def __init__(
        self,
        io_kwargs,
        fft_window=5,
        # input_meta_topic="pmudata.meta",
        kafka_topic='pmudata',
        channel_selection_idx=None,
        *args,
        **kwargs
    ):
        sample_msg = get_last_message_from_topic(kafka_topic, **io_kwargs)
        dt = 1 / sample_msg.cfg.get_data_rate()
        n_samples_fft = 2 ** int(np.ceil(np.log(fft_window / dt) / np.log(2)))

        TimeWindowApp.__init__(
            self,
            n_samples=n_samples_fft,
            input_topic=kafka_topic,
            io_kwargs=io_kwargs,
            auto_adjust_offset=False,
            channel_selection_idx=channel_selection_idx,
            *args,
            **kwargs)

        self.n_samples_store = 500

        consumer_seek_relative_offset(self.input_stream, -n_samples_fft - self.n_samples_store)


        self.freq_range = fftfreq(n_samples_fft, dt)
        self.em_freq_idx = (self.freq_range >= 0) & (self.freq_range <= 2)
        self.fft_tw = TimeWindow(n_samples=self.n_samples_store, n_cols=n_samples_fft, dtype=float)
        self.fft_tw._data[:] = 0
        self.run_fft = calculate_fft_spectrum

    def run_analysis(self, t, measurement):
        measurement = measurement.flatten()

        # Do not run FFT before the time window is filled up (the time window is initialized with np.nan).
        if not np.any(np.isnan(t)):

            time_stamp_fft = np.mean(t)
            # for fft_tw_, angle in zip(self.fft_tw, measurement.T):
            spectrum = self.run_fft(measurement)
            self.fft_tw.append(time_stamp_fft, spectrum)




class FFTViz(QWidget):
    def __init__(self, io_kwargs, fft_window=10, kafka_topic="pmudata", channel_selection_idx=None):
        super().__init__()

        fft_anl = FFTOnlineSingleChannel(
            fft_window=fft_window,
            kafka_topic=kafka_topic,
            io_kwargs=io_kwargs,
            channel_selection_idx=channel_selection_idx,
        )

        fft_anl_thread = threading.Thread(target=fft_anl.run, daemon=True)
        fft_anl_thread.start()

        # win = QtWidgets.QMainWindow()
        # win = self.window
        # win.setMinimumSize(640, 480)

        # d1 = QtWidgets.QDockWidget("1", win)
        # d2 = QtWidgets.QDockWidget("2", win)
        # d3 = QtWidgets.QDockWidget("3", win)
        # d3 = QtWidgets.QDockWidget("3", win)
        # win.addDockWidget(QtCore.Qt.LeftDockWidgetArea, d1)
        # win.addDockWidget(QtCore.Qt.BottomDockWidgetArea, d2)
        # win.addDockWidget(QtCore.Qt.BottomDockWidgetArea, d3)
        # win.addDockWidget(QtCore.Qt.BottomDockWidgetArea, d3)


        # win.setLayout(layout)
        # win.setWindowTitle("FFT")


        cols = sum(fft_anl.em_freq_idx)
        rows = fft_anl.fft_tw.n_samples

        def height_fun(tw=fft_anl.fft_tw):
            # tw = tws[channel_select.col_idx]
            # return np.sin(tw.get_time()*np.ones((cols, rows)))  #
            return abs(tw.get_col(fft_anl.em_freq_idx).T)*500#*fft_ctrl.z_plot_scale
            
            # return

        fft_plt = SurfacePlot(
            cols,
            rows,
            height_fun,
            col_ticks=[
                fft_anl.freq_range[fft_anl.em_freq_idx][0],
                1,
                fft_anl.freq_range[fft_anl.em_freq_idx][-1],
            ],
        )

        # fft_plt.show()
        # fft_plt.w.show()
        self.fft_plt = fft_plt

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(fft_plt.window)
        self.setLayout(layout)
        # d3.setWidget(fft_plt.w)
        # win.setCentralWidget(fft_plt.w)
        self.resize(640, 480)



# def run_fft_viz(*config_args, fft_window=5, channel_selection_idx=None):
#     config = load_config(*config_args)
#     # app = QtWidgets.QApplication(sys.argv)
#     fft_viz = FFTViz(
#         fft_window=fft_window,
#         kafka_topic=config['topics']['pmudata'],
#         io_kwargs=config["streaming"],
#         channel_selection_idx=channel_selection_idx,
#     )
#     fft_viz.show()

#     # app.exec()
#     # fft_viz.fft_anl.stop()
#     return fft_viz



class RunApp(QWidget):
    def __init__(self, config, run_app_func):
        self.tw_plots = []

        super().__init__()
        self.layout = QGridLayout()
        self.setLayout(self.layout)

        self.config = config
        self.run_app_func = run_app_func

        while True:
            pmu_data_frame = get_last_message_from_topic(
                topic=config['topics']['pmudata'],
                **config["streaming"],
            )
            if not pmu_data_frame is None:
                break
            else:
                time.sleep(1)

        pmu_tw = PMUTimeWindow(n_samples=1)
        pmu_tw.initialize_from_config_frame(pmu_data_frame.cfg)
        channel_names = []
        for i, row in enumerate(pmu_tw.tw.header):
            channel_names.append(':'.join([''.join(r) for r in row]))

        self.selector = ChannelSelect(channel_names)

        launch_button = QPushButton('Run')

        launch_button.clicked.connect(self.launch_app)

        self.layout.addWidget(self.selector)
        self.layout.addWidget(launch_button)
        self.selector.show()

        self.parameters = {'fft_window': 10}

    def launch_app(self):
        # print('Running app')
        # print(selector.selected_channels)
        channel_selection_idx = [self.selector.channel_to_idx[ch]
                                 for ch in self.selector.selected_channels]
        if len(self.selector.selected_channels) == 0:
            print('No channels selected!')
        else:
            for idx in channel_selection_idx:
                fft_viz = FFTViz(
                    fft_window=self.parameters['fft_window'],
                    kafka_topic=self.config['topics']['pmudata'],
                    io_kwargs=self.config["streaming"],
                    channel_selection_idx=[idx],
                )
                fft_viz.show()
                self.tw_plots.append(fft_viz)       



def run_fft_viz_launcher(*config_args, update_freq=25, **kwargs):
    config = load_config(*config_args)

    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    app = QtWidgets.QApplication(sys.argv)

    tw_runner = RunApp(config, lambda: 1)
    tw_runner.show()

    app.exec()
    return app



if __name__ == "__main__":

    # __file__ = r'C:\Users\hallvarh\PycharmProjects\ModeEstimation\src\plotting_fft_2.py'

    # run_fft_viz_launcher()
    config = load_config()

    app = QtWidgets.QApplication(sys.argv)
    fft_viz = FFTViz(
        fft_window=10,
        kafka_topic=config['topics']['pmudata'],
        io_kwargs=config["streaming"],
        channel_selection_idx=0,
    )
    fft_viz.show()
    app.exec()
    
