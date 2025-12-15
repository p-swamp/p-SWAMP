from PySide6 import QtWidgets
from pswamp.visualization.components.geo_plot_2d import GeoPlot2D
from pswamp.gui.components.channel_select import ChannelSelect
import numpy as np


class ChannelSelectMap(QtWidgets.QWidget):
    def __init__(self, channels, bus_names, bus_coords, countries=[]):
        super().__init__()

        layout = QtWidgets.QVBoxLayout()
        
        self.channel_select = ChannelSelect(channels)

        self.grid_plot = GeoPlot2D(
            update_freq=25,
            k=2,
            countries=countries,
            bus_kwargs=dict(
                bus_coords=bus_coords,
                bus_names=bus_names,
            ),
        )
        def update_channel_select_query(station):
            self.channel_select.filter_edit.setText(station)


        self.grid_plot.station_was_clicked.connect(update_channel_select_query)

        layout.addWidget(self.grid_plot.window)
        layout.addWidget(self.channel_select)
        
        self.setLayout(layout)


def main():

    import sys
    import pathlib
    pmu_data_example_folder = pathlib.Path(
        __file__).parents[4]/'examples'/'recorded_pmu_data'/'data'
    sys.path.append(str(pmu_data_example_folder))
    import load_pmu_coordinates
    bus_names, bus_coords = load_pmu_coordinates.load()
    bus_coords_3d = np.hstack([bus_coords, np.ones((len(bus_coords), 1))])

    app = QtWidgets.QApplication()
    channel_select_map = ChannelSelectMap(
        channels=bus_names,
        bus_names=bus_names,
        bus_coords=bus_coords,
        countries=['Norway'],
    )
    channel_select_map.show()
    app.exec()


if __name__ == '__main__':
    main()