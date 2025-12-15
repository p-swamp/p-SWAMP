from PySide6.QtWidgets import QWidget, QApplication, QVBoxLayout
from PySide6.QtCore import QTimer, QSize
from pswamp.visualization.time_window_plot import TimeSeriesPlot
from pswamp.utils.misc import flatten_array_insert_nan
from pswamp.app_templates.time_window_app import TimeWindowApp
import threading


class FreqPlot(QWidget):
    def __init__(self, config, update_freq=10):
        super().__init__()


        # self.col_idx_freq = self.tw_app.pmu_tw.tw.get_col_idx(measurement='f')

        self.tw_app = TimeWindowApp(
            kafka_kwargs=config['kafka'],
            input_topic=config['topics']['pmudata'],
            decoder_kwargs={"channel_selection": {'measurement': 'f'}},
            window_length=30,
            n_samples=None,
            auto_adjust_offset=True,
            # eval_freq=update_freq,
            # store_dataframes=False,
        )
        self.tw_app_thread = threading.Thread(target=self.tw_app.run, daemon=True)
        self.tw_app_thread.start()


        self.freq_ax = TimeSeriesPlot()
        self.freq_ax.plotWidget.setLabel('left', 'f [Hz]')
        self.freq_ax.plotWidget.setLabel('bottom', 'Time')
        pl = self.freq_ax.add_plot()

        layout = QVBoxLayout()
        layout.addWidget(self.freq_ax)
        self.setLayout(layout)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.start(1/update_freq*1000)

    
    def minimumSizeHint(self):
        return QSize(250, 150)

    def sizeHint(self):
        return QSize(250, 150) 


        
    
    def update_plots(self):
        self.freq_ax.plots[0].setData(
            *flatten_array_insert_nan(*self.tw_app.tw.get())
        )


if __name__ == '__main__':

    from pswamp import load_config
    config = load_config()

    app = QApplication()

    freq_plot = FreqPlot(config)
    freq_plot.show()

    app.exec()