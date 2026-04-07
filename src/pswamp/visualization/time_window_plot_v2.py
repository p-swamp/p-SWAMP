# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

import numpy as np
from pswamp.utils.load_config import load_config
from pswamp.gui.components.channel_select_geo import ChannelSelectMap
from pswamp.gui.components.channel_select import ChannelSelect
from pswamp.streaming import get_last_message_from_topic
from pswamp.visualization.components.date_time_axis import DateAxisItem
# from pswamp.visualization.time_window_plot_v2 import TimeWindowPlotV2
import threading
from PySide6 import QtWidgets, QtCore
import pyqtgraph as pg
import sys
from pswamp.app_templates.time_window_app import TimeWindowApp


class TimeWindowPlotV2(QtWidgets.QWidget):
    def __init__(self, tw, update_freq=10, n_max_plots=50, title="", datetime_xaxis=True, background_color=(30, 63, 64), *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.n_max_plots = n_max_plots
        self.tw = tw
        
        self.colors = lambda i: pg.intColor( i, hues=9, values=1, maxValue=255, minValue=150, maxHue=360, minHue=0, sat=255, alpha=255)
        self.channel_names = []
        self.pens = []
        for i, row in enumerate(self.tw.header):
            self.channel_names.append(':'.join([''.join(r) for r in row]))         
            self.pens.append(pg.mkPen(color=self.colors(i), width=2))

        self.graphWidget = pg.GraphicsLayoutWidget(show=True, title=title)
        self.graphWidget.setBackground(background_color)
        self.selected_channels = []

        self.plotWidget = self.graphWidget.addPlot()
        self.plotWidget.addLegend()

        if datetime_xaxis:
            axis = DateAxisItem(orientation='bottom')
            axis.attachToPlotItem(self.plotWidget)

        self.pl = []
        for i in range(min(n_max_plots, self.tw.n_cols)):
            new_pl = self.plotWidget.plot(self.tw.get_time(), np.nan*np.zeros(self.tw.n_samples))
            new_pl.hide()
            self.pl.append(new_pl)

        self.update_colors()
        # self.graphWidget.show()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(1000 // update_freq)

    def add_channel(self, index):
        if not isinstance(index, list):
            indices = [index]
        else:
            indices = index

        for index in indices:
            if len(self.selected_channels) < self.n_max_plots:
                self.selected_channels.append(index)
            else:
                print(f'Max number of channels {self.n_max_plots} selected.')
                return
        # self.pl[new_pl_idx].setPen(pg.mkPen(color=self.colors(index), width=2))
            new_channel_idx = len(self.selected_channels) - 1
            self.pl[new_channel_idx].show()
            # self.pl[new_channel_idx].opts['name'] = self.channel_names[index]
            # self.plotWidget.legend.addItem(self.pl[new_channel_idx], self.channel_names[index])
        self.update_colors()

    def remove_channel(self, index):
        if not isinstance(index, list):
            indices = [index]
        else:
            indices = index

        for index in indices:
            if not index in self.selected_channels:
                continue
            # print(f'Removing {index} from {str(self.selected_channels)}')
            self.selected_channels.remove(index)
            self.pl[len(self.selected_channels)].hide()
            self.plotWidget.legend.removeItem(self.pl[len(self.selected_channels)].name())
        self.update_colors()

    def update_colors(self):
        # print(f'Legend has {len(self.plotWidget.legend.items)} entries')
        for pl in self.pl:  # [:len(self.selected_channels)]:
            # dir(pl)
            # print(pl.name())
            self.plotWidget.legend.removeItem(pl.name())
        # for item in self.plotWidget.legend.items:
            # print(item)
        # # self.plotWidget.legend.items = []
        # while self.plotWidget.legend.layout.count() > 0:
        #     self.plotWidget.legend.layout.removeAt(0)
        # print(f'Legend has {len(self.plotWidget.legend.items)} entries')

        for i, (pl, selected_channel) in enumerate(zip(self.pl, self.selected_channels)):
            # print('Adding plot')
            # pl.show()
            
            # self.plotWidget.legend.removeItem(pl.name())

            pl.setPen(self.pens[selected_channel])
            pl.opts['name'] = self.channel_names[selected_channel]
            self.plotWidget.legend.addItem(pl, self.channel_names[selected_channel])


        # print(f'Legend has {len(self.plotWidget.legend.items)} entries')

    def update(self):
        time_stamp = self.tw.get_time()
        plot_data = self.tw.get_col()
        for i, (pl, selected_channel) in enumerate(zip(self.pl, self.selected_channels)):
            if not pl.isVisible() or np.all(np.isnan(plot_data[:, selected_channel])):
                continue
            pl.setData(time_stamp, plot_data[:, selected_channel])


class TimeWindowPlotGUI(QtWidgets.QMainWindow):
    def __init__(
            self,
            io_kwargs,
            input_topic="pmudata",
            pmu_coords_topic="pmu_coords_topic",
            countries=[],
            update_freq=25,
            # phasor_selection=None,
            n_max_plots=50,
            include_map=True,
            *args,
            **kwargs
    ):
        super().__init__()
        
        tw_app = TimeWindowApp(
            io_kwargs=io_kwargs,  # config["streaming"],
            **kwargs,
        )
        # pmu_tw.initialize()

        p_2 = threading.Thread(target=tw_app.run, daemon=True)
        p_2.start()

        tw_plot = TimeWindowPlotV2(tw_app.tw, update_freq=update_freq, n_max_plots=n_max_plots)
        tw_plot.show()

        channels = []
        for row in tw_app.tw.header:
            channels.append(':'.join([''.join(r) for r in row]))

        # channel_select = ChannelSelect(channels)
        if include_map:
            bus_names, bus_coords = get_last_message_from_topic(
                pmu_coords_topic, **io_kwargs
            )
                    
            channel_select_map = ChannelSelectMap(
                channels=channels,
                bus_names=bus_names,
                bus_coords=bus_coords,
                countries=countries,
            )
            channel_select_map.show()
            self.channel_select = channel_select_map.channel_select
        else:
            self.channel_select = ChannelSelect(channels)

        def show_channel(item):
            index = [self.channel_select.channel_to_idx[item_.data(0)] for item_ in item]
            tw_plot.add_channel(index)

        def hide_channel(item):
            index = [self.channel_select.channel_to_idx[item_.data(0)] for item_ in item]
            tw_plot.remove_channel(index)
            
        self.channel_select.item_was_selected = show_channel
        self.channel_select.item_was_unselected = hide_channel    

        self.setCentralWidget(tw_plot.graphWidget)
        
        gui_dock = QtWidgets.QDockWidget("", self)
        gui_dock.setWidget(channel_select_map if include_map else self.channel_select)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea if include_map else QtCore.Qt.BottomDockWidgetArea, gui_dock)
        

        # Executed after plot window is closed
        # tw_app.stop()

    


def run_time_window_plot(*config_args, update_freq=25, n_max_plots=50, **kwargs):
    config = load_config(*config_args)

    app = QtWidgets.QApplication(sys.argv)

    time_window_plot_gui = TimeWindowPlotGUI(
        input_topic=config['topics']['pmudata'],
        pmu_coords_topic=config['topics']['pmu.coords'],
        io_kwargs=config["streaming"],
        countries=config['geo_data']['countries'] if 'geo_data' in config and 'countries' in config['geo_data'] else [],
        update_freq=update_freq,
        n_max_plots=n_max_plots,
        **kwargs
    )
    time_window_plot_gui.show()

    app.exec()
    return app



if __name__ == '__main__':
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
