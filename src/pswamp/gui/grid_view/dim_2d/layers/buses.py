import ezdxf
from io import StringIO
from pswamp.database import get_from_database
import numpy as np
import threading
from pswamp.utils.pmu_time_window import PMUTimeWindow
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.components.phasor_plot import PhasorPlot
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
import uuid
from pswamp.utils.get_station_coords import load_bus_coords_for_current_stations
import pswamp.visualization.components.single_line_diagram as sld


class BusesLayer:
    def __init__(self, parent, config, sld_id=None) -> None:
        self.config = config
        self.plotWidget = parent.plotWidget
        self.k = 1. # 2 if geo else 1
        self.sld_id = sld_id
        # bus_names, bus_coords_3d = load_bus_coords_for_current_stations(
        #     config, return_3d=True, geo=geo)
        
        # bus_coords_3d[:, 1] *= self.k

        # self.x = bus_coords_3d[:, 0]
        # self.y = bus_coords_3d[:, 1]
        # self.z = bus_coords_3d[:, 2]

        self.read_sld_data(config["database"])

        # self.colors = lambda i: pg.intColor(
        #     i,
        #     hues=9,
        #     values=1,
        #     maxValue=255,
        #     minValue=150,
        #     maxHue=360,
        #     minHue=0,
        #     sat=255,
        #     alpha=255,
        # )

        # use_colors = False
        # color = np.ones((len(bus_coords_3d), 4))
        # color[:, -1] = 0.5
        # if use_colors:
        #     color = (
        #         np.array([self.colors(i).getRgb() for i in range(len(bus_coords_3d))])
        #         / 255
        #     )
        self.bus_scatter = self.add_scatter_plot(self.bus_coords)
        self.plotWidget.addItem(self.bus_scatter)

    def add_scatter_plot(self, bus_coords):
        return pg.ScatterPlotItem(
            x=bus_coords[:, 0], y=bus_coords[:, 1], brush=pg.mkBrush(('white')))  # pen=pg.mkPen('w'), )

    def remove_layer(self):
        self.plotWidget.removeItem(self.bus_scatter)


    def read_sld_data(self, db_kwargs):
        sld_data = get_from_database(db_kwargs, "single_line_diagrams")
        dxf_data = sld_data[sld_data["name"] == self.sld_id]["data"].values[-1]
        dxf_file_stream = StringIO(dxf_data)
        doc = ezdxf.read(dxf_file_stream)

        # tables = ["bus"] + self.branch_types

        # model_data = {table: get_from_database(db_kwargs, table) for table in tables}
        # model_data["bus"]
        # model_data = {key: val for key, val in model_data.items() if val is not None}

        # self.bus_data = pd.DataFrame(columns=model_data['buses'][0], data=model_data['buses'][1:])
        # self.lines_data = pd.DataFrame(columns=model_data['lines'][0], data=model_data['lines'][1:])

        # self.trafos_data = pd.DataFrame(columns=model_data['transformers'][0], data=model_data['transformers'][1:])

        self.bus_data = get_from_database(db_kwargs, "bus")
        # self.lines_data = model_data["line"]
        # self.trafos_data = model_data["trafo"]

        self.bus_names, self.bus_coords = sld.get_buses(
            doc, self.bus_data["name"].to_numpy()
        )


class BusNamesLayer(BusesLayer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bus_name_text = []
        for coord, bus_name in zip(self.bus_coords, self.bus_names):
            txtitem1= self.add_text(coord, bus_name)
            self.bus_name_text.append(txtitem1)
            self.plotWidget.addItem(txtitem1)
    
    def add_text(self, coord, text):
            text_item = pg.TextItem(anchor=(0, 0), text="{}".format(text), color=(127, 127, 127))
            text_item.setPos(coord[0], coord[1])
            return text_item

    def remove_layer(self):
        for txt in self.bus_name_text:
            self.plotWidget.removeItem(txt)


if __name__ == '__main__':
    from pswamp.gui.grid_view.dim_2d.base_plot_layers import GridBasePlot2D
    from pswamp import load_config
    import pswamp
    from pathlib import Path
    sample_dataset_path = Path(pswamp.__file__).parent/'test_utils/sample_datasets/n44'

    config = load_config()
    config['sld_data'] = {'line_data_path': sample_dataset_path/'sld.dxf'}
    config['model_data_path'] = sample_dataset_path/'model_data.json'

    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot2D(
        geo=False,
    )
    grid_plot.window.show()

    # layer_instance = LineLayer(grid_plot, config, geo=False)
    # layer_settings = CountriesLayerSettings(layer_instance)
    # layer_settings.show()
    # layer_instance.remove_layer()

    app.exec()
