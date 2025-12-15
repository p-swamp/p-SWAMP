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


class LineLayer:
    def __init__(self, parent, config, geo=True) -> None:
        self.config = config
        self.k = 2 if geo else 1
        self.parent = parent
        plotWidget = parent.plotWidget

        self.read_sld_data(config, geo)

        self.lines_plot = self.add_line_plots(self.line_paths_flat)
        self.trafos_plot = self.add_line_plots(self.trafo_paths_flat)
        
        plotWidget.addItem(self.lines_plot)
        plotWidget.addItem(self.trafos_plot)

    def read_sld_data(self, config, geo):
        data_key = 'geo_data' if geo else 'sld_data'
        if not (data_key in config and 'line_data_path' in config[data_key]):
            raise Exception(
                'Line data path not found, layer could not be shown.')

        line_data_path = config[data_key]['line_data_path']
        if line_data_path.suffix == '.npz':
            raise Exception('Line data must be a dxf-file to show LineLayer.')
        assert line_data_path.suffix == '.dxf'

        with open(line_data_path) as file:
            dxf_file = file.read()

        with open(config['model_data_path']) as file:
            model_data = json.load(file)

        self.bus_data = pd.DataFrame(columns=model_data['bus'][0], data=model_data['bus'][1:])
        self.lines_data = pd.DataFrame(columns=model_data['line'][0], data=model_data['line'][1:])

        self.trafos_data = pd.DataFrame(columns=model_data['trafo'][0], data=model_data['trafo'][1:])

        dxf_file
        dxf_file_stream = StringIO(dxf_file)
        doc = ezdxf.read(dxf_file_stream)
        self.bus_names, self.bus_coords = get_buses(doc, self.bus_data['name'].to_numpy())

        self.line_paths, self.line_midpoints = get_branches_xy_by_matching_buses(doc, self.lines_data)
        self.line_segment_lengths = np.array([len(xy_) for xy_ in self.line_paths])
        self.n_lines = len(self.line_paths)

        self.trafo_paths, self.trafo_midpoints = get_branches_xy_by_matching_buses(doc, self.trafos_data)
        self.trafo_segment_lengths = np.array([len(xy_) for xy_ in self.trafo_paths])
        self.n_trafos = len(self.trafo_paths)

        self.line_paths_flat = flatten_list_insert_nan(self.line_paths)
        self.trafo_paths_flat = flatten_list_insert_nan(self.trafo_paths)

        self.lines_from_bus_idx = lookup_strings(self.lines_data['from_bus'], self.bus_names)
        self.lines_to_bus_idx = lookup_strings(self.lines_data['to_bus'], self.bus_names)

        self.trafos_from_bus_idx = lookup_strings(self.trafos_data['from_bus'], self.bus_names)
        self.trafos_to_bus_idx = lookup_strings(self.trafos_data['to_bus'], self.bus_names)
            
    def add_line_plots(self, pos, line_width=1, color='white'):
        return pg.PlotCurveItem(
            pos[:, 0], pos[:, 1], connect='finite', pen=pg.mkPen(color=color, width=line_width))  # QtGui.QColor(color))

    def remove_layer(self):
        self.parent.plotWidget.removeItem(self.lines_plot)
        self.parent.plotWidget.removeItem(self.trafos_plot)

    def get_branches_from_buses(self, bus_idx):
        line_idx = np.isin(self.lines_from_bus_idx, bus_idx) + \
            np.isin(self.lines_to_bus_idx, bus_idx)
        trafo_idx = np.isin(self.trafos_from_bus_idx, bus_idx) + \
            np.isin(self.trafos_to_bus_idx, bus_idx)

        return np.where(line_idx)[0], np.where(trafo_idx)[0]

    def __del__(self):
        self.remove_layer()


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

    layer_instance = LineLayer(grid_plot, config, geo=False)
    # layer_settings = CountriesLayerSettings(layer_instance)
    # layer_settings.show()
    # layer_instance.remove_layer()

    app.exec()
