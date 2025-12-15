import numpy as np
from pswamp.utils.pmu_time_window import PMUTimeWindowOnline
from pswamp.utils.load_config import load_config
import threading
import PySide6.QtCore as QtCore
import PySide6.QtWidgets as QtWidgets
import pyqtgraph as pg
import sys
from pswamp.visualization.components.date_time_axis import DateAxisItem
from pswamp.utils.time_window_labeled import TimeWindowLabeled, GrowingTimeWindowLabeled
from pswamp.app_templates.time_window_app import TimeWindowApp


class TimeSeriesPlot(pg.GraphicsLayoutWidget):
    """Basic  time series plot. Adds date axis, background color, legend, etc."""
    def __init__(self, title="", datetime_xaxis=True, background_color=(30, 63, 64)):
        super().__init__(title=title)
        self.setBackground(background_color)

        self.plotWidget = self.addPlot()
        self.plotWidget.addLegend()
        if datetime_xaxis:
            self.axis = DateAxisItem(orientation='bottom')
            self.axis.attachToPlotItem(self.plotWidget)

        self.plots = []

    def add_plot(self, color='lightgray', width=2, **kwargs):
        pen = pg.mkPen(color=color, width=width)
        # plot = self.plotWidget.plot([0, 0], [0, 0], pen=pen, **kwargs)
        plot = pg.PlotCurveItem([0, 0], [0, 0], pen=pen, connect='finite', **kwargs)
        self.plotWidget.addItem(plot)
        self.plots.append(plot)
        return plot


class TimeWindowPlot(QtWidgets.QWidget):
    """Time window plot with automatic updating from most recent values in time window."""
    def __init__(self, tw, update_freq=10, title="", datetime_xaxis=True, background_color=(30, 63, 64), col_idx=None, col_sel=None, *args, **kwargs):
        super().__init__()
            
        self.tw = tw
        
        self.channel_names = []
        for row in self.tw.header:
            self.channel_names.append(':'.join([''.join(r) for r in row]))            

        self.graphWidget = pg.GraphicsLayoutWidget(title=title)
        self.graphWidget.setBackground(background_color)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.graphWidget)
        self.setLayout(layout)

        self.colors = lambda i: pg.intColor( i, hues=9, values=1, maxValue=255, minValue=150, maxHue=360, minHue=0, sat=255, alpha=255)

        self.plotWidget = self.graphWidget.addPlot()
        self.plotWidget.addLegend()

        if datetime_xaxis:
            axis = DateAxisItem(orientation='bottom')
            axis.attachToPlotItem(self.plotWidget)

        if col_idx is not None:
            self.col_idx = col_idx
        elif col_sel is not None:
            self.col_idx = np.array([self.tw.get_col_idx(col)[0] for col in col_sel])
        else:
            self.col_idx = np.arange(self.tw.n_cols)
            

        self.pl = []
        for i in self.col_idx:
            # print(i)
            pen = pg.mkPen(color=self.colors(i), width=2)
            pl = self.plotWidget.plot(
                [0, 0], [0, 0], pen=pen, name=self.channel_names[i]
            )
            self.pl.append(pl)

        

        # self.graphWidget.show()
        if update_freq is not None:
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self.update)
            self.timer.start(1000 // update_freq)

    def update(self):
        time_stamp = self.tw.get_time()
        if len(time_stamp) > 0 and np.any(~np.isnan(time_stamp)):
            plot_data = self.tw.get_col(self.col_idx)
            for i, pl in enumerate(self.pl):
                if not pl.isVisible() or np.all(np.isnan(plot_data[:, i])):
                    continue
                    # try:
                pl.setData(time_stamp, plot_data[:, i])
                    # except Exception:
                        # pass
    
    def request_update(self):
        self.update()



class AnglePlot(TimeWindowPlot):
    def __init__(self, *args, subtract_mean=True, **kwargs):
        self.subtract_mean = subtract_mean
        super().__init__(*args, **kwargs)
    def update(self):
        time_stamp = self.tw.get_time()
        angles = np.angle(self.tw.get_col())

        if np.any(np.isnan(time_stamp)):
            not_nan_idx = ~np.isnan(time_stamp)
            time_stamp = time_stamp[not_nan_idx]
            angles = angles[not_nan_idx, :]
        
        # Linear interpolation for nan values
        mask = np.isnan(angles)
        angles[mask] = np.interp(np.flatnonzero(mask), np.flatnonzero(~mask), angles[~mask])

        angles = np.unwrap(angles, axis=1)
        angles = np.unwrap(angles, axis=0)
        if self.subtract_mean:
            angles -= np.mean(angles, axis=1)[:, None]
        
        for i, pl in enumerate(self.pl):
            pl.setData(time_stamp, angles[:, i])



def plot_time_window(
    kafka_kwargs,
    # kafka_topic="pmudata",
    update_freq=25,
    # phasor_selection=None,
    # channel_selection_idx=None,
    # auto_adjust_offset=True,
    # window_length=60,
    # n_samples=None,
    # *args,
    **kwargs
):

    # pmu_tw = PMUTimeWindowOnline(
    #     *args,
    #     kafka_kwargs,
    #     kafka_topic=kafka_topic,
    #     # phasor_selection=phasor_selection,
    #     auto_adjust_offset=auto_adjust_offset,
    #     window_length=window_length,
    #     n_samples=n_samples,
    #     channel_selection_idx=channel_selection_idx,
    #     **kwargs
    # )
    # pmu_tw.initialize()
    tw_app = TimeWindowApp(
        kafka_kwargs=kafka_kwargs,  # config['kafka'],
        **kwargs,
    )
        # t_end=70,
        # output_topic="islanding",
        # auto_adjust_offset=False)

    p_2 = threading.Thread(target=tw_app.run, daemon=True)
    p_2.start()

    app = QtWidgets.QApplication(sys.argv)

    tw_plot = TimeWindowPlot(tw_app.tw, update_freq=update_freq)
    tw_plot.show()

    app.exec()

    # Executed after plot window is closed
    tw_app.stop()

    return app


def run_time_window_plot(*config_args, update_freq=25, channel_selection_idx=None, **kwargs):
    config = load_config(*config_args)
    plot_time_window(
        input_topic=config['topics']['pmudata'],
        kafka_kwargs=config['kafka'],
        update_freq=update_freq,
        channel_selection_idx=channel_selection_idx,
        # time_window_type=TimeWindowLabeled,
        **kwargs
    )


if __name__ == "__main__":
    config = load_config()
    run_online = False
    if run_online:
        run_time_window_plot(config)
    # else:
    #     from pswamp.test_utils.sample_datasets.mock_case import run_mock_case, stop_mock_case
    #     # config['kafka']['bootstrap_servers'] = 'localhost:50000'
    #     mock_case = run_mock_case(config)
    #     run_time_window_plot(config)
    #     stop_mock_case(config)
    else:
        from pswamp.test_utils.sample_datasets.n44.n44_rtsim_offline import\
            run_n44_rtsim_offline, stop_case
        
        config['kafka']['consumers_seek_to_beginning'] = True

        events = [
            (1, ('line', 'L3244-6500', 'disconnect')),
            (1, ('line', 'L3244-6500', 'connect')),            
        ]

        run_n44_rtsim_offline(config, events, t_end=10)
        run_time_window_plot(config, channel_selection={'measurement': 'f'})
        stop_case(config)