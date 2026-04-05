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

from pswamp.gui.components.run_app_dialogue import RunApp
from PySide6 import QtWidgets
import sys
from pswamp.utils.pmu_time_window import PMUTimeWindowOnline
from pswamp import load_config
import threading
from pswamp.visualization.time_window_plot import TimeWindowPlot


def plot_time_window(
    io_kwargs,
    kafka_topic="pmudata",
    update_freq=25,
    phasor_selection=None,
    channel_selection_idx=None,
    auto_adjust_offset=True,
    window_length=30,
    n_samples=None,
    *args,
    **kwargs
):

    pmu_tw = PMUTimeWindowOnline(
        *args,
        io_kwargs,
        kafka_topic=kafka_topic,
        # phasor_selection=phasor_selection,
        auto_adjust_offset=auto_adjust_offset,
        window_length=window_length,
        n_samples=n_samples,
        channel_selection_idx=channel_selection_idx,
        **kwargs
    )
    pmu_tw.initialize()

    p_2 = threading.Thread(target=pmu_tw.run, daemon=True)
    p_2.start()

    # app = QtWidgets.QApplication(sys.argv)

    tw_plot = TimeWindowPlot(pmu_tw.tw, update_freq=update_freq)
    tw_plot.show()

    # app.exec()

    # Executed after plot window is closed
    # pmu_tw.stop()

    return tw_plot


class RunAppLocal(RunApp):
    def __init__(self, *args, **kwargs):
        self.tw_plots = []
        super().__init__(*args, **kwargs)
    
    def launch_app(self):
        # print('Running app')
        # print(selector.selected_channels)
        channel_selection_idx = [self.selector.channel_to_idx[ch] for ch in self.selector.selected_channels]
        if len(self.selector.selected_channels) == 0:
            print('No channels selected!')
        else:
            self.tw_plots.append(plot_time_window(
                kafka_topic=self.config['topics']['pmudata'],
                io_kwargs=self.config["streaming"],
                # update_freq=update_freq,
                channel_selection_idx=channel_selection_idx,
                # **kwargs
            ))



def run_time_window_plot(*config_args, update_freq=25, **kwargs):
    config = load_config(*config_args)

    app = QtWidgets.QApplication(sys.argv)

    tw_runner = RunAppLocal(config, lambda: 1)
    tw_runner.show()
    
    app.exec()
    return app


if __name__ == "__main__":
    config = load_config()
    run_online = False
    if run_online:
        run_time_window_plot(config)
    else:
        from pswamp.test_utils.sample_datasets.mock_case import run_mock_case, stop_mock_case
        # config["streaming"]['bootstrap_servers'] = 'localhost:50000'
        mock_case = run_mock_case(config)
        run_time_window_plot(config)
        stop_mock_case(config)
