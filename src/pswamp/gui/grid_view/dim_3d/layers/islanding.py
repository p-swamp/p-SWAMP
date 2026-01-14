import numpy as np
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindowOnline
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.components.phasor_plot import PhasorPlot
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations, load_bus_coords_for_stations
import pyqtgraph.opengl as gl
from pswamp.streaming.kafka_extras import Consumer
from pswamp.styles import colors as global_colors
from pswamp.utils.gl import set_gl_options

class Islanding:
    def __init__(self, parent, bus_coords_3d, geo=True, color_scheme='islanding', n_max_islands=8) -> None:
        self.plotWidget = parent.plotWidget

        self.k = 2 if geo else 1
        bus_coords_3d[:, 1] *= self.k

        self.uuid = uuid.uuid4()
        self.parent = parent

        self.newest_message = None

        self.stopped = False        
        
        self.x = bus_coords_3d[:, 0]
        self.y = bus_coords_3d[:, 1]
        self.z = bus_coords_3d[:, 2]*0

        colors = getattr(global_colors, color_scheme)        

        self.n_max_islands = n_max_islands
        self.bus_scatters = [self.add_scatter_plot(colors[1+i]) for i in range(self.n_max_islands)]
        [self.plotWidget.addItem(bus_scatter) for bus_scatter in self.bus_scatters]


    def add_scatter_plot(self, color):

        bus_scatter = gl.GLScatterPlotItem(
            pos=np.vstack([[], [], []]).T,
            color=global_colors.gl_color(color),
            size=50
        )
        # bus_scatter.setGLOptions('translucent')
        return bus_scatter
    
    def hide(self):
        [bus_scatter.hide() for bus_scatter in self.bus_scatters]

    def show(self):
        [bus_scatter.show() for bus_scatter in self.bus_scatters]

    def update_scatter(self, islands=None, z=None):
        if self.newest_message is None and islands is None:
            return
        elif islands is None:
            islands = self.newest_message.value['result']['islands']
            
        for island_nr, island_buses in enumerate(islands):
            if island_nr >= self.n_max_islands:
                break
            # print(island_nr, island_buses)
            self.bus_scatters[island_nr].setData(pos=np.vstack([
                self.x[island_buses],
                self.y[island_buses],
                self.z[island_buses] + (z[island_nr] if z is not None else 0),
            ]).T)
        for plot_nr in range(len(islands), self.n_max_islands):
            # print(f'Removing plots: {plot_nr}')
            self.bus_scatters[plot_nr].setData(pos=np.array([[], [], []]).T)
        # self.bus_scatter.update(freq)
    
    def remove_layer(self):
        self.stopped = True
        [self.plotWidget.removeItem(bus_scatter) for bus_scatter in self.bus_scatters]


class IslandingOnline(Islanding):
    def __init__(self, parent, config, geo=True) -> None:
        self.config = config
        bus_names, bus_coords_3d = load_bus_coords_for_current_stations(config, geo=geo, return_3d=True)

        self.consumer = Consumer(
            config['topics']['islanding'], **config["streaming"])

        def get_islanding_messages():
            for message in self.consumer:
                if self.stopped:
                    break
                self.newest_message = message

        consumer_thread = threading.Thread(
            target=get_islanding_messages, daemon=True)
        consumer_thread.start()

        super().__init__(parent, bus_coords_3d, geo)
        parent.update_funs[self.uuid] = self.update_scatter

    def add_scatter_plot(self, color):
        bus_scatter = super().add_scatter_plot(color)
        set_gl_options(self.config, bus_scatter)
        return bus_scatter
        

class IslandingLayerSettings(QtWidgets.QWidget):
    def __init__(self, target_layer):
        self.target_layer = target_layer
        super().__init__()

        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(0, 100)

        def slider_change(val):
            pass
            # self.target_layer.z_scale = val/10
        
        slider.valueChanged.connect(slider_change)
        layout.addWidget(slider)
        self.show()


if __name__ == '__main__':
    from pswamp.styles import colors
    from pswamp.gui.grid_view.dim_3d.base_plot_layers import GridBasePlot3D
    from pswamp import load_config
    from pswamp.gui.grid_view.dim_3d.layers import CountriesLayer, CountriesLayerSettings

    config = load_config()

    # bus_coords_3d = np.vstack([
    #     np.random.randn(10) + 16,
    #     np.random.randn(10) + 60,
    #     np.random.randn(10)*0,
    # ]).T

    bus_coords_3d = np.array([
        [7.55075278, 61.2862977, 0],
        [11.19006573, 59.24652311, 0],
        [10.53343092, 63.6414062, 0],
        [7.27922741, 58.27522422, 0],
        [17.38804198, 68.4347851, 0],
        [6.31222967, 59.52307759, 0],
        [28.1055445,  70.44836522, 0],
    ])

    app = pg.mkQApp()
    base_plot = GridBasePlot3D(live_plot=False)
    base_plot.window.show()

    countries_layer = CountriesLayer(parent=base_plot, config=config)
    countries_layer_settings = CountriesLayerSettings(countries_layer)
    countries_layer_settings.show()
    
    islanding_layer = Islanding(parent=base_plot, bus_coords_3d=bus_coords_3d)
    # islanding_layer.newest_message = type('', (), {'value': {'result': {'islands': }}})
    islands = [1, 1, 2, 0, 0, 3]
    islanding_layer.update_scatter(islands)

    # islanding_layer_settings = IslandingLayerSettings(islanding_layer)
    app.exec()