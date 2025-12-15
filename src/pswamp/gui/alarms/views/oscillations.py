import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore, QtGui
from pswamp import load_config
from pswamp.coordination.alarm_handling import AlarmMonitor
from pswamp.app_templates.time_window_app import TimeWindowApp
import numpy as np
from pswamp.visualization.time_window_plot import TimeSeriesPlot
import threading
import datetime
from pswamp.streaming.kafka_extras import consumer_seek_relative_offset
import time
from pswamp.visualization.voltage_phasor_plot import VoltagePhasorPlot
from pswamp.visualization.components.phasor_plot import PhasorPlotFast, PhasorPlotFastFancy, PhasorBasePlot, xy_from_phasors
from pswamp.utils.misc import convert_time_stamp_to_seconds, flatten_array_insert_nan
from pswamp.app_templates.snapshot_app import SnapshotApp
from pswamp.styles import colors
from pswamp.gui.grid_view.dim_3d.layers import Islanding
from pswamp.gui.grid_view.dim_3d.base_plot_layers import GridBasePlot3DLayers
from pswamp.utils.get_station_coords import load_bus_coords_for_stations, load_bus_coords_for_current_stations
from pswamp.gui.grid_view.dim_3d.layers.lines import LineLayer
from pswamp.styles.colors import gl_color
from pswamp.models.line import Line
from pswamp.gui.alarms.views.interactive import InteractiveAlarmView
from pswamp.gui.alarms.views.islanding import IslandingResultKeeper as AppResultKeeper
from pswamp.utils.misc import lookup_strings
from pswamp.visualization.eigenvalue_plot import EigenvaluePlot


class OscillationAlarmView(InteractiveAlarmView):
    def __init__(self, config, *args, **kwargs):
        self.initialized = False

        self.simplified_alarm_views = config['misc']['simplified_alarm_views'] if 'misc' in config and 'simplified_alarm_views' in config['misc'] else False
        channel_selection={'measurement': 'f'} if self.simplified_alarm_views else None
        super().__init__(config, *args, update_freq=10, define_layout=False, channel_selection=channel_selection,**kwargs)
        
        self.islanding_results = AppResultKeeper(
            kafka_kwargs=config['kafka'],
            input_topic=config['topics']['modeestimation'],
            t_start=self.time_stamp_start,
            t_end=self.t_end_seconds,
            # eval_freq=update_freq,
        )
        self.islanding_data_rate = self.islanding_results.get_input_data_rate()
        self.pmu_data_rate = self.tw_app.get_input_data_rate()

        # Get indices of voltages and frequencies
        self.col_idx_freq = self.tw_app.tw.get_col_idx(measurement='f')
        self.col_idx_mag = []
        self.col_idx_ang = []
        stations_to_plot = []
        for station_name in self.tw_app.tw.header['station'][self.col_idx_freq]:
            # idx_freq_ = self.tw_app.tw.get_col_idx(station=station_name.strip(), measurement='f')
            idx_mag_ = self.tw_app.tw.get_col_idx(station=station_name.strip(), measurement='v_Magnitude')
            idx_ang_ = self.tw_app.tw.get_col_idx(station=station_name.strip(), measurement='v_Angle')
            if len(idx_mag_ > 0) and len(idx_mag_) == len(idx_ang_):  #  and len(idx_mag_) == len(idx_freq_):
                # self.col_idx_freq.append(idx_freq_[0])
                self.col_idx_mag.append(idx_mag_[0])
                self.col_idx_ang.append(idx_ang_[0])
                stations_to_plot.append(station_name.strip())

        self.col_idx_mag = np.array(self.col_idx_mag)
        self.col_idx_ang = np.array(self.col_idx_ang)

        self.islanding_res_thread = threading.Thread(target=self.islanding_results.run, daemon=True)
        self.islanding_res_thread.start()
        
        app_channel_selection_idx = self.islanding_results.get_sample_data_frame()['parameters']['channel_selection_idx']
        self.stations = [row[0] for row in self.tw_app.tw.header[app_channel_selection_idx]]
        self.station_idx = lookup_strings(self.stations, self.tw_app.tw.header['station'][self.col_idx_freq])

        while len(self.freq_ax.plots) > 0:  #  + 1:
            remove_item = self.freq_ax.plots.pop()
            self.freq_ax.plotWidget.removeItem(remove_item)

        
        self.phasor_ax = PhasorBasePlot()
        # self.phasor_ax.add_plot()

        self.eigenvalue_plot = EigenvaluePlot()

        # Update grid view layers
        self.grid_view_islanding_layers = {}
        self.grid_view_islanding_line_layers = {}
        if self.grid_view is not None:
            for view_name, view in self.grid_view.views.items():
                if not isinstance(view, GridBasePlot3DLayers):
                    continue

                # self.bus_names, bus_coords_3d = load_bus_coords_for_current_stations(config, geo=view.geo, return_3d=True)
                bus_coords_3d = load_bus_coords_for_stations(config, self.stations, geo=view.geo, return_3d = True)
                self.grid_view_islanding_layers[view_name] = Islanding(view, bus_coords_3d, view.geo, color_scheme='oscillations', n_max_islands = len(self.stations))
                self.grid_view_islanding_layers[view_name].update_scatter([[i] for i in range(len(self.stations))])
                
                try:
                    self.line_calculator = Line(config, self.tw_app.get_config_frame())
                    self.grid_view_islanding_line_layers[view_name] = LineLayer(view, config, view.geo)
                    
                    view.set_non_base_layers_visibility(False)
                    view.set_layer_visibility('Base layers', 'Static line data', False)

                except Exception:
                    self.line_calculator = None
                
        self.define_layout()
        self.initialized = True

    def define_layout(self):
        try:
            layout_outer = QtWidgets.QVBoxLayout()
            layout = QtWidgets.QHBoxLayout()    
            layout.addWidget(self.freq_ax)
            layout.addWidget(self.eigenvalue_plot.graphWidget)            
            layout.addWidget(self.phasor_ax)
            layout.setStretchFactor(self.phasor_ax, 0)
            layout.setStretchFactor(self.eigenvalue_plot.graphWidget, 0)
            layout.setStretchFactor(self.freq_ax, 1)
            layout_outer.addLayout(layout)
            layout_outer.addWidget(self.time_slider)
            self.setLayout(layout_outer)
        except Exception as e:
            pass
                


    def update_plots(self, value):
        if not self.initialized:
            return

        if len(self.islanding_results.storage) == 0:
            return
        
        app_data_frame_idx = min(len(self.islanding_results.storage) - 1, round(value*self.islanding_data_rate/self.pmu_data_rate))
        app_data_frame = self.islanding_results.storage[app_data_frame_idx]
        eigenvalues = app_data_frame['result']['eigenvalues']
        mode_shapes = app_data_frame['result']['mode_shapes']
        channel_selection_idx = app_data_frame['parameters']['channel_selection_idx']
        
        self.freq_ax_inf_line.setValue(self.tw_app.tw.get_time()[value])

        self.eigenvalue_plot.update('plot_1', 'Eigenvalues', eigenvalues)

        n_measurements = mode_shapes.shape[0]
        i_plot = len(self.freq_ax.plots)
        while len(self.freq_ax.plots) < n_measurements:  #  + 1:
            self.phasor_ax.add_plot(color=colors.oscillations[i_plot+1], name=self.stations[i_plot])
            self.freq_ax.add_plot(color=colors.oscillations[i_plot+1], name=self.stations[i_plot])
            i_plot += 1

        while len(self.freq_ax.plots) > n_measurements:  #  + 1:
            remove_item = self.phasor_ax.plots.pop()
            self.phasor_ax.plotWidget.removeItem(remove_item)
            remove_item = self.freq_ax.plots.pop()
            self.freq_ax.plotWidget.removeItem(remove_item)

        # mag = self.tw_app.tw.get_col(self.col_idx_mag)[value]
        # ang = self.tw_app.tw.get_col(self.col_idx_ang)[value]
        # phasors = mag*np.exp(1j*ang)/max(mag)
        phasors = mode_shapes[:, 0]
        max_ph_idx = np.argmax(abs(phasors))
        phasors /= phasors[max_ph_idx]
        phasors_x, phasors_y = xy_from_phasors(phasors)
        
        time_stamps, measurements = self.tw_app.tw.get(channel_selection_idx)
        frequency = self.tw_app.tw.get_col(self.col_idx_freq)
        
        # representative_line_layer = next(iter(self.grid_view_islanding_line_layers.values())) if self.grid_view_islanding_line_layers else None
        # n_lines = representative_line_layer.n_lines if representative_line_layer else 0
        node_z = np.zeros(len(self.col_idx_freq))
        # line_colors = np.zeros((n_lines, 4))
        for i_plot in range(n_measurements):  #  + 1):

        #     if i_plot == 0:
        #         current_island_idx = np.delete(self.col_idx_freq, np.concatenate(islanding_idx)) if len(islanding_idx) > 0 else slice(None)
        #     else:
        #         current_island_idx = islanding_idx[i_plot - 1]
            
            
            self.phasor_ax.plots[i_plot].setData(
                # *flatten_array_insert_nan(x.T, y.T))
                phasors_x[i_plot], phasors_y[i_plot])
            
        #     # print(len([item for i, item in enumerate(self.voltage_phasor_base_plot.items()) if item.__class__.__name__ == 'PlotCurveItem']))
        #     mean_freq_island = np.mean(frequency[value, current_island_idx])

        #     node_z[current_island_idx] = mean_freq_island - 50
                
                
        #     # if i_island == 0:
        #     # print(phasors[0])
            # print(time_stamps.shape, measurements[:, i_plot].shape)

            self.freq_ax.plots[i_plot].setData(
                # *flatten_array_insert_nan(time_stamps, measurements[:, [i_plot]])
                np.array(time_stamps), measurements[:, i_plot]
            )

        #     for line_layer in self.grid_view_islanding_line_layers.values():
        #         line_idx, trafo_idx = line_layer.get_branches_from_buses(current_island_idx) if len(islanding_idx) > 0 else (slice(None), slice(None))
        #         line_layer.set_line_colors(colors=gl_color(colors.oscillations[i_plot]), idx=line_idx)
        #         line_layer.set_trafo_colors(colors=gl_color(colors.oscillations[i_plot]), idx=trafo_idx)
                
                # line_layer.update_trafo_colors()

        node_z = (frequency[value, :] - 50)*2 + 1
        for line_layer in self.grid_view_islanding_line_layers.values():
            # line_layer.set_node_z(node_z*5 + 1)
            line_layer.set_node_z(node_z)

        for layer in self.grid_view_islanding_layers.values():
            layer.update_scatter(islands=[[i] for i in range(len(self.stations))], z=node_z[self.station_idx])

        # Set color of disconnected lines
        if self.line_calculator is not None:
            disconnected_lines = np.where(self.line_calculator.disconnected(self.tw_app.data_frame_storage[value]))[0]
            # connectable_lines = np.where((self.line_calculator.connectable(self.tw_app.pmu_data_frame_storage[value])))[0]
            for line_layer in self.grid_view_islanding_line_layers.values():
                line_layer.reset_line_colors()
                line_layer.reset_trafo_colors()
                line_layer.set_line_colors(colors=[1, 0, 0, 1], idx=disconnected_lines)
                # line_layer.set_line_colors(colors=[0, 1, 0, 1], idx=connectable_lines)
                line_layer.update_line_colors()
                line_layer.update_trafo_colors()

    def close_view(self):
        for view in self.grid_view_islanding_layers.values():
            view.remove_layer()

        for view in self.grid_view_islanding_line_layers.values():
            view.remove_layer()

        if self.grid_view is None:
            return
        
        if self.line_calculator is not None:  # Means that layers were hidden during init
            for view_name, view in self.grid_view.views.items():
                view.set_non_base_layers_visibility(True)
                view.set_layer_visibility('Base layers', 'Static line data', True)




if __name__ == '__main__':
    from pswamp.gui.grid_view.grid_view_container import GridViewContainer
    config = load_config()

    run_online = True
    if run_online:
        config['kafka']['consumers_seek_to_beginning'] = True
        config['kafka']['bootstrap_servers'] = 'localhost:40000'
        config['kafka']['bootstrap_servers'] = 'localhost:45001'

        alarm_monitor = AlarmMonitor(
            kafka_kwargs=config['kafka'],
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

        config['kafka']['consumers_seek_to_beginning'] = False
        app = QtWidgets.QApplication()

        grid_view = GridViewContainer(config, True)
        grid_view.show()
        
        alarm_view = OscillationAlarmView(
            config, alarm_uuid=alarm_uuid, alarm_data=alarm_data, grid_view=grid_view)
        alarm_view.show()
        app.exec()

    else:
        config = load_config()
        # from pswamp.test_utils.mock_case import run_mock_case, stop_mock_case, KafkaProducer
        from pswamp.test_utils.sample_datasets.n44_mock_case import run_mock_case, stop_mock_case
        config['kafka']['bootstrap_servers'] = 'localhost:50000'


        app_data_frames = [{
            'parameters': {
                'eval_freq': 1,
                'channel_selection_idx': [1, 10, 4],
            },
            'result': {
                'time_stamp': time_stamp,
                'eigenvalues': np.array([0.1 + 1j, 0.1 - 1j, 5 + 0.1j, 5 - 0.1j]),
                'mode_shapes': np.array([[]]),
            }
        } for time_stamp in np.arange(0, 10)]

        mock_case = run_mock_case(config, topic_data={'modeestimation': app_data_frames})

        alarm_data = {
            "time_stamp": 5.0,
            "time_stamp_end": 10.0,
        }
        alarm_uuid = 1

        app = QtWidgets.QApplication()

        grid_view = GridViewContainer(config, False)
        grid_view.show()

        alarm_view = OscillationAlarmView(
            config, alarm_uuid=alarm_uuid, alarm_data=alarm_data, grid_view=grid_view)
        alarm_view.show()

        # producer = KafkaProducer(**config['kafka'])
        # [producer.send('islanding', df) for df in islanding_data_frames]       
        
        app.exec()

        stop_mock_case(config)