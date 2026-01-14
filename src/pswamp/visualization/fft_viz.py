import threading
# import ctypes
import sys
from PySide6 import QtWidgets, QtCore
from pswamp.visualization.components.surface_plot import SurfacePlot
# from pswamp.visualization.components.channel_select import ChannelSelect
from pswamp.gui.components.single_channel_select import SingleChannelSelect
from pswamp.monitoring.fft import FFTOnline
# from pswamp.visualization.time_window_plot import TimeWindowPlot
import pyqtgraph as pg
# from qtrangeslider import QRangeSlider
from pswamp.visualization.components.threshold_adjust import ThresholdAdjustment
from pswamp.utils.load_config import load_config


def fft_viz(
    io_kwargs,
    fft_window=5,
    kafka_topic="pmudata",
    channel_selection_idx=None,
    channel_selection={'measurement': 'f'},
    **kwargs,
):

    fft_anl = FFTOnline(
        fft_window=fft_window,
        kafka_topic=kafka_topic,
        io_kwargs=io_kwargs,
        channel_selection=channel_selection,
        channel_selection_idx=channel_selection_idx,
        **kwargs,
    )

    fft_anl_thread = threading.Thread(target=fft_anl.run, daemon=True)
    fft_anl_thread.start()

    app = QtWidgets.QApplication(sys.argv)
    # user32 = ctypes.windll.user32
    # screen_size = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    win = QtWidgets.QMainWindow()
    win.setMinimumSize(640, 480)
    # win_rel_size = 1 / 3
    # qtRectangle = win.frameGeometry()
    # coords = qtRectangle.getCoords()
    # print(coords)
    # win.setGeometry(
    #     coords[0], coords[1], 640, 480
    #     # screen_size[0] * (1 - win_rel_size) / 2,
    #     # screen_size[1] * (1 - win_rel_size) / 2,
    #     # screen_size[0] * win_rel_size,
    #     # screen_size[1] * win_rel_size,
    # )

    # d1 = QtWidgets.QDockWidget("1", win)
    d2 = QtWidgets.QDockWidget("2", win)
    d3 = QtWidgets.QDockWidget("3", win)
    # d3 = QtWidgets.QDockWidget("3", win)
    # win.addDockWidget(QtCore.Qt.LeftDockWidgetArea, d1)
    win.addDockWidget(QtCore.Qt.BottomDockWidgetArea, d2)
    win.addDockWidget(QtCore.Qt.BottomDockWidgetArea, d3)
    # win.addDockWidget(QtCore.Qt.BottomDockWidgetArea, d3)


    layout = QtWidgets.QHBoxLayout()
    win.setLayout(layout)
    win.setWindowTitle("FFT")

    win.show()

    tw = fft_anl.tw

    # channel_select = ChannelSelect(pmu_tw.station_names, pmu_tw.channel_names)
    channel_names = []
    for i, row in enumerate(tw.header):
        channel_names.append(':'.join([''.join(r) for r in row]))

    channel_select = SingleChannelSelect(channel_names)

    d2.setWidget(channel_select)

    # FFT Controls
    fft_ctrl = FFTControlWidget(fft_anl)
    d3.setWidget(fft_ctrl)

    # tw_plot = TimeWindowPlot(pmu_tw.tw)
    # d1.setWidget(tw_plot.graphWidget)

    # cols = tw.n_cols
    cols = sum(fft_anl.em_freq_idx)
    rows = fft_anl.fft_tw[0].n_samples

    def height_fun(tws=fft_anl.fft_tw, channel_select=channel_select):
        tw = tws[channel_select.selected_channel_idx()]
        # return np.sin(tw.get_time()*np.ones((cols, rows)))  #
        return abs(tw.get_col(fft_anl.em_freq_idx).T)*fft_ctrl.z_plot_scale
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
    # d3.setWidget(fft_plt.w)
    win.setCentralWidget(fft_plt.w)

    app.exec()

    fft_anl.stop()

    return app


class FFTControlWidget(QtWidgets.QWidget):
    """
    For setting scale and thresholds for FFT App.
    """

    def __init__(self, fft_anl):
        super().__init__()
        self.fft_anl = fft_anl

        layout = QtWidgets.QVBoxLayout()

        self.z_plot_scale = 20
        depthSpin_plot = pg.SpinBox(
            value=self.z_plot_scale, step=1, bounds=[0, 1000], delay=0, int=False
        )
        depthSpin_plot.valueChanged.connect(self.scale_plot_change)
        layout.addWidget(depthSpin_plot)
        
        self.z_scale = 10
        depthSpin = pg.SpinBox(
            value=self.z_scale, step=1, bounds=[0, 100000], delay=0, int=False
        )
        depthSpin.valueChanged.connect(self.scale_change)
        layout.addWidget(depthSpin)
        
        # range_slider = QRangeSlider(QtCore.Qt.Horizontal)
        self.threshold_adjustment = ThresholdAdjustment()
        range_slider = self.threshold_adjustment.range_slider
        self.alert_slider_val, self.emergency_slider_val = range_slider.value()
        range_slider.valueChanged.connect(self.slider_change)
        
        
        # layout.addWidget(range_slider)
        layout.addWidget(self.threshold_adjustment)
        
        self.setLayout(layout)
        self.show()

        update_freq = 10
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.redraw_indicator)
        self.timer.start(1000 // update_freq)

    def redraw_indicator(self):
        indicator = self.fft_anl.max_amplitude*(self.z_scale)
        if not indicator == 0:
            self.threshold_adjustment.indicator_slider.setValue(indicator)
        # print(indicator)

    def slider_change(self, val):
        self.alert_slider_val = val[0]
        self.emergency_slider_val = val[1]
        self.update_thresholds()

    def scale_change(self, val):
        self.z_scale = val
        self.update_thresholds()

    def update_thresholds(self):
        self.fft_anl.threshold_alert = self.alert_slider_val/(self.z_scale)
        self.fft_anl.threshold_emergency = self.emergency_slider_val/(self.z_scale)

    def scale_plot_change(self, val):
        self.z_plot_scale = val


def run_fft_viz(*config_args, fft_window=5, channel_selection_idx=None):
    config = load_config(*config_args)
    fft_viz(
        io_kwargs=config["streaming"],
        fft_window=fft_window,
        kafka_topic=config['topics']['pmudata'],
        channel_selection_idx=channel_selection_idx,
    )



if __name__ == "__main__":

    # __file__ = r'C:\Users\hallvarh\PycharmProjects\ModeEstimation\src\plotting_fft_2.py'

    config = load_config()
    run_online = False
    if run_online:
        run_fft_viz(config)
    else:
        from pswamp.test_utils.sample_datasets.mock_case import run_mock_case, stop_mock_case
        # config["streaming"]['bootstrap_servers'] = 'localhost:50000'
        mock_case = run_mock_case(config)
        run_fft_viz(config)
        stop_mock_case(config)
