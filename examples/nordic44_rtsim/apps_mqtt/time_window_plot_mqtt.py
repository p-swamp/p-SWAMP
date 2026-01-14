from pswamp.visualization.time_window_plot import run_time_window_plot
from pswamp.app_templates.time_window_app import TimeWindowApp
import threading
from pswamp.visualization.time_window_plot import TimeWindowPlot
from PySide6 import QtWidgets
import sys
from pswamp import load_config
from pswamp.streaming import BaseIO


def plot_time_window(
    io_kwargs,
    update_freq=25,
    **kwargs
):

    io = BaseIO(io_kwargs=io_kwargs)
    tw_app = TimeWindowApp(
        io=io,
        **kwargs,
    )
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
        io_kwargs=config['streaming'],
        update_freq=update_freq,
        channel_selection_idx=channel_selection_idx,
        # time_window_type=TimeWindowLabeled,
        **kwargs
    )


# if __name__ == "__main__":
#     config = load_config()
#     run_online = False
#     if run_online:
#         run_time_window_plot(config)


if __name__ == '__main__':
    run_time_window_plot('../config.toml', channel_selection={"measurement": "f"}, window_length=10)