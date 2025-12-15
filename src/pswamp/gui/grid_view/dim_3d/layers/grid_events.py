import numpy as np
import threading
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations
import pyqtgraph.opengl as gl
from pswamp.streaming.kafka_extras import KafkaConsumer
from pswamp.utils.misc import lookup_strings
from pswamp.utils.gl import set_gl_options


class GridEvents:
    def __init__(self, parent, config, geo=True) -> None:
        self.config = config
        self.plotWidget = parent.plotWidget

        self.k = 2 if geo else 1
        self.uuid = uuid.uuid4()
        self.parent = parent

        bus_names, bus_coords_3d = load_bus_coords_for_current_stations(config, geo=geo, return_3d=True)
        self.stations = np.array([bus_name.strip() for bus_name in bus_names])
        bus_coords_3d[:, 1] *= self.k

        self.affected_stations = np.zeros_like(self.stations, dtype=bool)

        self.consumer = KafkaConsumer(
            config['topics']['grid.events'], **config['kafka'])
        self.stopped = False
        self.newest_message = None

        consumer_thread = threading.Thread(target=self.get_messages, daemon=True)
        consumer_thread.start()

        self.x = bus_coords_3d[:, 0]
        self.y = bus_coords_3d[:, 1]
        self.z = bus_coords_3d[:, 2]*0

        self.scatter_plot = self.add_scatter_plot()  # self.colors(i)) for i in range(self.n_max_islands)]
        self.plotWidget.addItem(self.scatter_plot)
        # self.plotWidget.addItem(self.bus_lines)

        parent.update_funs[self.uuid] = self.update_scatter

    def get_messages(self):
        for message in self.consumer:
            if self.stopped:
                break
            for event in message.value['result']['events']:
                
                station_idx = lookup_strings(event['stations'], self.stations)
                self.affected_stations[station_idx] = event['type'] == 'disconnect'
                    
                
    
    def add_scatter_plot(self, color='b'):
        bus_scatter = gl.GLScatterPlotItem(
            pos=np.vstack([[], [], []]).T,
            # color=color,
            size=25,
        )
        set_gl_options(self.config, bus_scatter)
        return bus_scatter

    def update_scatter(self):
        # if not np.any(self.affected_stations):
            # return
        
        self.scatter_plot.setData(pos=np.vstack([
            self.x[self.affected_stations],
            self.y[self.affected_stations],
            self.z[self.affected_stations],
        ]).T)

    def remove_layer(self):
        self.stopped = True
        self.plotWidget.removeItem(self.scatter_plot)
