# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from PySide6.QtWidgets import QWidget, QGridLayout, QPushButton, QApplication
import sys
from pswamp.utils.load_config import load_config
import multiprocessing as mp
from pswamp.visualization.fft_viz import run_fft_viz
from pswamp.monitoring.n4sid import run_n4sid
# from pswamp.monitoring.ssi import run_ssi
# from pswamp.monitoring.prony import run_prony
from pswamp.visualization.n4sid_viz import run_n4sid_viz
from pswamp.visualization.time_window_plot import run_time_window_plot as run_time_window_plot_v1
from pswamp.visualization.time_window_plot_v15 import run_time_window_plot as run_time_window_plot_v15
from pswamp.visualization.time_window_plot_v2 import run_time_window_plot as run_time_window_plot_v2

from pswamp.visualization.voltage_heatmap import run_voltage_heatmap
from pswamp.visualization.freq_heatmap import run_freq_heatmap
from pswamp.visualization.voltage_phasor_plot import run_voltage_phasor_plot
from pswamp.monitoring.islanding import run_islanding_application
from pswamp.gui.components.run_app_dialogue import RunApp



class AppLauncher(QWidget):
    """Creates a list of buttons for launching applications."""
    def __init__(self, config):
        self.config = config
        QWidget.__init__(self)
        self.layout = layout = QGridLayout()
        self.setLayout(layout)

        # services = ['FFT', 'N4SID', 'Time series plot']

        
        # button = QPushButton('FFT')
        # def clicked_fun():
        #     self.open_run_app_dialogue_with_channel_select(run_fft_viz)
        # button.clicked.connect(clicked_fun)
        # layout.addWidget(button, 0, 0)
        # self.app_dialogues = []
        button = QPushButton('FFT')
        button.setToolTip(
            '''Visualization for power oscillations. Based on Fast Fourier
            Transform.''')
        def clicked_fun():
            print('Launching FFT')
            # fft.main(ip, port)
            self.p = mp.Process(target=run_fft_viz, args=(config,))
            self.p.start()
        button.clicked.connect(clicked_fun)
        layout.addWidget(button, 0, 0)

        button = QPushButton('Mode Estimation Viz')
        button.setToolTip(
            '''Visualization of mode estimates, which shows eigenvalues in
            complex plane and observability mode shapes. Will only show results
            if a mode estimator is running (e.g., N4SID or SSI-COV).''')

        def clicked_fun():
            self.p = mp.Process(target=run_n4sid_viz, args=(config,))
            self.p.start()
        button.clicked.connect(clicked_fun)
        layout.addWidget(button, 0, 1)
        
        button = QPushButton('N4SID')
        button.setToolTip(
            '''Mode estimation based on system identification (N4SID). Produces
            estimates of eigenvalues and observability mode shapes. Low damping
            will cause "emergency status" and trigger alarms.''')
        def clicked_fun():
            self.open_run_app_dialogue_with_channel_select(run_n4sid)
        button.clicked.connect(clicked_fun)
        layout.addWidget(button, 1, 0)
        # self.app_dialogues = []

        # button = QPushButton('SSI')
        # button.setToolTip(
        #     '''Mode estimation based on system identification (SSI-COV). Produces
        #     estimates of eigenvalues and observability mode shapes. Low damping
        #     will cause "emergency status" and trigger alarms.''')

        # def clicked_fun():
        #     print('Launching SSI')
        #     self.open_run_app_dialogue_with_channel_select(run_ssi)

        #     # p.join()
        # button.clicked.connect(clicked_fun)
        # layout.addWidget(button, 1, 1)
        # self.app_dialogues = []

        button = QPushButton('Time window plot V1')
        button.setToolTip(
            '''Time window plot, variant 1: Channels are selected from a GUI,
            and plotted in a separate process.''')
        def clicked_fun():
            self.open_run_app_dialogue_with_channel_select(run_time_window_plot_v1, params={('Window length'): ('window_length', 30)})
        # def clicked_fun():
            # self.p = mp.Process(target=run_time_window_plot_v1, args=(config,))
            # self.p.start()
        button.clicked.connect(clicked_fun)
        layout.addWidget(button, 2, 0)

        # button = QPushButton('Time window plot V1.5')
        # # button.setToolTip(
        # #     '''Time window plot, variant 2: Similar to V1, except that the plot
        # #     runs in the same process.''')

        # def clicked_fun():
        #     self.p = mp.Process(target=run_time_window_plot_v15, args=(config,))
        #     self.p.start()
        # button.clicked.connect(clicked_fun)
        # layout.addWidget(button, 2, 1)
        
        button = QPushButton('Time window plot V2')
        button.setToolTip(
            '''Time window plot, variant 2: Similar to variant 1, but channels can
            be selected from the map.''')
        def clicked_fun():
            self.p = mp.Process(target=run_time_window_plot_v2, args=(config,))
            self.p.start()
        button.clicked.connect(clicked_fun)
        layout.addWidget(button, 2, 1)

        button = QPushButton('Frequency heatmap')
        button.setToolTip(
            '''Visualization: A heat map indicating frequency variations throughout the system.''')

        def clicked_fun():
            print('Launching Frequency heatmap')
            # fft.main(ip, port)
            self.p = mp.Process(target=run_freq_heatmap, args=(config,))
            self.p.start()
            # p.join()
        button.clicked.connect(clicked_fun)
        layout.addWidget(button, 3, 0)

        # button = QPushButton('Voltage heatmap')
        # def clicked_fun():
        #     print('Launching Voltage heatmap')
        #     # fft.main(ip, port)
        #     self.p = mp.Process(target=run_voltage_heatmap, args=(config,))
        #     self.p.start()
        #     # p.join()
        # button.clicked.connect(clicked_fun)
        # layout.addWidget(button, 3, 1)

        button = QPushButton('Voltage phasor plot')
        button.setToolTip(
            '''Visualization: A phasor plot showing the voltage phasors in the system.''')

        def clicked_fun():
            print('Launching Voltage phasor plot')
            # fft.main(ip, port)
            self.p = mp.Process(target=run_voltage_phasor_plot, args=(config,))
            self.p.start()
            # p.join()
        button.clicked.connect(clicked_fun)
        layout.addWidget(button, 3, 1)

        button = QPushButton('Islanding detection')
        button.setToolTip(
            '''Islanding detection application. Produces an alarm when islanding is detected.''')
        
        def clicked_fun():
            print('Launching Islanding Detection')
            self.p = mp.Process(target=run_islanding_application, args=(config,))
            self.p.start()
            # p.join()
        button.clicked.connect(clicked_fun)
        layout.addWidget(button, 4, 0)
        
        # self.app_dialogues = []

        # button = QPushButton('Prony')
        # button.setToolTip(
        #     '''Prony Method application..''')
        
        # def clicked_fun():
        #     print('Launching Prony')
        #     self.open_run_app_dialogue_with_channel_select(run_prony)

        #     # p.join()
        # button.clicked.connect(clicked_fun)
        # layout.addWidget(button, 4, 1)
        
        self.app_dialogues = []

    def open_run_app_dialogue_with_channel_select(self, run_app_func, params={}):
        app_dialogue = RunApp(self.config, run_app_func, params)
        app_dialogue.show()
        
        self.app_dialogues.append(app_dialogue)


def run_app_launcher(config_arg):
    config = load_config(config_arg)
    app = QApplication(sys.argv)
    # screen = RunApp(config)
    # screen.show()
    screen = AppLauncher(config)
    screen.show()
    app.exec()


if __name__ == '__main__':
    config = load_config()
    run_app_launcher(config)
