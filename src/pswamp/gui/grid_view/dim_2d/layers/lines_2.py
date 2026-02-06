from io import StringIO
from PySide6 import QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
from pswamp.utils.single_line_diagram import load_dxf
import ezdxf
from pswamp.visualization.components.single_line_diagram import get_buses, get_branches_xy_by_matching_buses
from pswamp.utils.misc import flatten_list_insert_nan
import numpy as np
import json
import pandas as pd
from pswamp.utils.misc import lookup_strings
from pswamp.database import get_from_database


class LineLayer:
    def __init__(self, parent, config, sld_id=None) -> None:
        self.config = config
        
        self.sld_id = sld_id
        
        try:
            self.k = 1  # config["single_line_diagrams"][self.sld_data_key]["aspect_ratio"]            
        except KeyError:
            self.k = 1
            
        self.parent = parent
        plotWidget = parent.plotWidget

        self.branch_types = ["line", "trafo"]

        self.read_sld_data(config["database"])
        

        self.branch_plots = {
            key: self.add_line_plots(val["paths_flat"])
            for key, val in self.branch_data.items()
        }
        # self.lines_plot = self.add_line_plots(self.line_paths_flat)
        # self.trafos_plot = self.add_line_plots(self.trafo_paths_flat)
        
        for plot in self.branch_plots.values():
            plotWidget.addItem(plot)
        # plotWidget.addItem(self.trafos_plot)

    def read_sld_data(self, db_kwargs):
        # sld_data = db_kwargs["single_line_diagrams"]
        # if not (self.sld_data_key in sld_data and 'data_path' in sld_data[self.sld_data_key]):
        #     raise Exception(
        #         'SLD data path not found, layer could not be shown.')

        # sld_data_path = sld_data[self.sld_data_key]['data_path']
        # assert sld_data_path.suffix == '.dxf'

        # with open(sld_data_path) as file:
        #     dxf_file = file.read()

        sld_data = get_from_database(db_kwargs, "single_line_diagrams")
        dxf_data = sld_data[sld_data["name"] == self.sld_id]["data"].values[-1]
        dxf_file_stream = StringIO(dxf_data)
        doc = ezdxf.read(dxf_file_stream)

        tables = ["bus"] + self.branch_types

        model_data = {table: get_from_database(db_kwargs, table) for table in tables}
        model_data["bus"]
        # model_data = {key: val for key, val in model_data.items() if val is not None}

        # self.bus_data = pd.DataFrame(columns=model_data['buses'][0], data=model_data['buses'][1:])
        # self.lines_data = pd.DataFrame(columns=model_data['lines'][0], data=model_data['lines'][1:])

        # self.trafos_data = pd.DataFrame(columns=model_data['transformers'][0], data=model_data['transformers'][1:])

        self.bus_data = model_data["bus"]
        # self.lines_data = model_data["line"]
        # self.trafos_data = model_data["trafo"]
        self.branch_data = {}

        self.bus_names, self.bus_coords = get_buses(doc, self.bus_data['name'].to_numpy())

        for key in self.branch_types:            
            if key not in model_data or model_data[key] is None:
                continue
            branch_data = {}
            branch_data["paths"], branch_data["midpoints"] = (
                get_branches_xy_by_matching_buses(doc, model_data[key])
            )
            branch_data["segment_lengths"] = np.array(
                [len(xy_) for xy_ in branch_data["paths"]]
            )
            branch_data["n"] = len(branch_data["paths"])
            branch_data["paths_flat"] = flatten_list_insert_nan(
                branch_data["paths"])
            
            branch_data["from_bus_idx"] = lookup_strings(
                model_data[key]["from_bus"], self.bus_names
            )
            branch_data["to_bus_idx"] = lookup_strings(
                model_data[key]["to_bus"], self.bus_names
            )

            self.branch_data[key] = branch_data
        # self.line_paths, self.line_midpoints = get_branches_xy_by_matching_buses(doc, self.lines_data)
        # self.line_segment_lengths = np.array([len(xy_) for xy_ in self.line_paths])
        # self.n_lines = len(self.line_paths)

        # self.trafo_paths, self.trafo_midpoints = get_branches_xy_by_matching_buses(doc, self.trafos_data)
        # self.trafo_segment_lengths = np.array([len(xy_) for xy_ in self.trafo_paths])
        # self.n_trafos = len(self.trafo_paths)

        # self.line_paths_flat = flatten_list_insert_nan(self.line_paths)
        # self.trafo_paths_flat = flatten_list_insert_nan(self.trafo_paths)

        # self.lines_from_bus_idx = lookup_strings(self.lines_data['from_bus'], self.bus_names)
        # self.lines_to_bus_idx = lookup_strings(self.lines_data['to_bus'], self.bus_names)

        # self.trafos_from_bus_idx = lookup_strings(self.trafos_data['from_bus'], self.bus_names)
        # self.trafos_to_bus_idx = lookup_strings(self.trafos_data['to_bus'], self.bus_names)
            
    def add_line_plots(self, pos, line_width=1, color='white'):
        return pg.PlotCurveItem(
            pos[:, 0], pos[:, 1], connect='finite', pen=pg.mkPen(color=color, width=line_width))  # QtGui.QColor(color))

    def remove_layer(self):
        for plot in self.branch_plots.values():
            self.parent.plotWidget.removeItem(plot)
        # self.parent.plotWidget.removeItem(self.lines_plot)
        # self.parent.plotWidget.removeItem(self.trafos_plot)

    def get_branches_from_buses(self, bus_idx):
        line_idx = np.isin(self.lines_from_bus_idx, bus_idx) + \
            np.isin(self.lines_to_bus_idx, bus_idx)
        trafo_idx = np.isin(self.trafos_from_bus_idx, bus_idx) + \
            np.isin(self.trafos_to_bus_idx, bus_idx)

        return np.where(line_idx)[0], np.where(trafo_idx)[0]

    def __del__(self):
        try:
            self.remove_layer()
        except RuntimeError:
            pass


if __name__ == '__main__':
    from pswamp.gui.grid_view.dim_2d.base_plot_layers import GridBasePlot2D
    from pswamp import load_config
    import pswamp
    from pathlib import Path
    # sample_dataset_path = Path(pswamp.__file__).parent/'test_utils/sample_datasets/n44'

    config = load_config()
    # config['sld_data'] = {'line_data_path': sample_dataset_path/'sld.dxf'}
    # config['model_data_path'] = sample_dataset_path/'model_data.json'

    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot2D(
        geo=True,
    )
    grid_plot.window.show()

    layer_instance = LineLayer(grid_plot, config, geo=True)
    # layer_settings = CountriesLayerSettings(layer_instance)
    # layer_settings.show()
    # layer_instance.remove_layer()

    app.exec()
