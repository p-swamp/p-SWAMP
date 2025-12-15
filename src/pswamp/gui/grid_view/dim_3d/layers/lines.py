from io import StringIO
from PySide6 import QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data
from pswamp.utils.single_line_diagram import load_dxf
import ezdxf
from pswamp.visualization.components.single_line_diagram import get_buses
from pswamp.utils.misc import flatten_list_insert_nan
import pyqtgraph.opengl as gl
import numpy as np
from pswamp.gui.grid_view.dim_2d.layers.lines import LineLayer as LineLayer2D
from pswamp.utils.misc import lookup_strings
from pswamp.utils.gl import set_gl_options


class LineLayer(LineLayer2D):       
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lines_z_map = self.build_z_map(self.lines_data, self.line_paths)
        self.trafos_z_map = self.build_z_map(self.trafos_data, self.trafo_paths)

        self.line_colors = 0.5*np.ones((self.n_lines, 4))
        self.trafo_colors = 0.5*np.ones((self.n_trafos, 4))

    def build_z_map(self, data, paths):
        
        points_per_line = np.array([len(xy_) for xy_ in paths])

        n_line_points = sum(points_per_line) + len(points_per_line)
        n_buses = len(self.bus_names)
        line_z_mat = np.zeros((n_line_points, n_buses))        
        
        ix = 0
        for (i_line, line), line_path in zip(data.iterrows(), paths):
            # print(line)
            from_bus_idx = lookup_strings(line['from_bus'], np.array(self.bus_names))
            to_bus_idx = lookup_strings(line['to_bus'], np.array(self.bus_names))
            line_idx = slice(ix, ix + len(line_path))
            ix += len(line_path) + 1
            segment_lengths = np.sqrt(np.sum((line_path[1:, :] - line_path[:-1, :])**2, axis=1))

            cumsum = np.insert(np.cumsum(segment_lengths), 0, 0)
            cumsum /= cumsum[-1] if cumsum[-1] > 0 else 1
            
            line_z_mat[line_idx, from_bus_idx] = 1 - cumsum
            line_z_mat[line_idx, to_bus_idx] = cumsum

        # line_points = line_z_mat.dot(frequency)
        return line_z_mat

    def update_line_z_coords(self, node_z):
        new_z = self.lines_z_map.dot(node_z)
        pos = np.hstack([self.line_paths_flat, new_z[:, None]])
        self.lines_plot.setData(pos=pos)

    def update_trafo_z_coords(self, node_z):
        new_z = self.trafos_z_map.dot(node_z)
        pos = np.hstack([self.trafo_paths_flat, new_z[:, None]])
        self.trafos_plot.setData(pos=pos)
    
    def set_node_z(self, z):
        self.update_line_z_coords(z)
        self.update_trafo_z_coords(z)

    def add_line_plots(self, pos, line_width=2, color='gray'):
        pl = gl.GLLinePlotItem(
            pos=pos, width=line_width, color=color, antialias=False
        )
        set_gl_options(self.config, pl)
        return pl
        
    def reset_line_colors(self):
        self.line_colors = 0.5*np.ones((self.n_lines, 4))

    def reset_trafo_colors(self):
        self.trafo_colors = 0.5*np.ones((self.n_trafos, 4))
    
    def set_line_colors(self, colors, idx=slice(None)):
        self.line_colors[idx, :] = colors

    def update_line_colors(self):
        line_colors_agg = np.repeat(self.line_colors, self.line_segment_lengths + 1, axis=0)
        self.lines_plot.setData(color=line_colors_agg)

    def set_trafo_colors(self, colors, idx=slice(None)):
        self.trafo_colors[idx, :] = colors

    def update_trafo_colors(self):
        colors_agg = np.repeat(self.trafo_colors, self.trafo_segment_lengths + 1, axis=0)
        self.trafos_plot.setData(color=colors_agg)




if __name__ == '__main__':
    from pswamp.gui.grid_view.dim_3d.base_plot_layers import GridBasePlot3D
    from pswamp import load_config
    import pswamp
    from pathlib import Path
    sample_dataset_path = Path(pswamp.__file__).parent/'test_utils/sample_datasets/n44'

    config = load_config()
    # config['sld_data'] = {'line_data_path': sample_dataset_path/'sld.dxf'}
    # config['sld_data'] = {'line_data_path': sample_dataset_path/'sld.dxf'}
    # config['model_data_path'] = sample_dataset_path/'model_data.json'

    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot3D(
        geo=True,
        # background_color=(255, 255, 255)
    )
    grid_plot.window.show()


    layer_instance = LineLayer(grid_plot, config, geo=True)
    n_lines = layer_instance.n_lines
    line_V_n = layer_instance.bus_data['V_n'][lookup_strings(layer_instance.lines_data['from_bus'], layer_instance.bus_data['name'])]
    # lookup_strings(layer_instance.lines_data['from_bus'], layer_instance.bus_data['name'])


    amp = np.random.randn(44)*0.2
    freq = np.random.randn(44)*0.5
    phas = np.random.randn(44)*0.1
    
    import time
    def update_colors():
        while True:
            # line_colors = np.hstack([np.random.randn(n_lines, 3), np.ones((n_lines, 1))])
            # line_colors = np.hstack([np.repeat([[0.5, 0.5, 0.5]], n_lines, axis=0), np.ones((n_lines, 1))])
            # line_colors[:20, :] = [0.1, 0.1, 0.9, 1]
            # line_colors = np.ones((n_lines, 4))*line_V_n.to_numpy()[:, None]/np.max(line_V_n)
            # line_colors[:, -1] = 0.2
            # layer_instance.set_line_colors(colors=line_colors)
            bus_idx = lookup_strings('6700', layer_instance.bus_names)
            line_idx, trafo_idx = layer_instance.get_branches_from_buses([bus_idx])
            
            # line_colors[line_idx] = [0.2, 1, 0.2, 1]
            layer_instance.set_line_colors(colors=[0.2, 1, 0.2, 1], idx=line_idx)
            layer_instance.set_trafo_colors(
                colors=[0.2, 1, 0.2, 1], idx=trafo_idx)

            # line_idx, trafo_idx = layer_instance.get_branches_from_buses([10, 11, 12, 13, 14, 15])
            # layer_instance.set_line_colors(colors=[1, 0.2, 0.2, 1], idx=line_idx)

            layer_instance.update_line_colors()
            layer_instance.update_trafo_colors()


            z = amp*np.sin(time.time()*freq + phas)
            layer_instance.set_node_z(z)

            
            time.sleep(0.02)

    import threading
    thread = threading.Thread(target=update_colors)
    thread.start()
    # layer_settings = CountriesLayerSettings(layer_instance)
    # layer_settings.show()

    # layer_instance.remove_layer()

    app.exec()
