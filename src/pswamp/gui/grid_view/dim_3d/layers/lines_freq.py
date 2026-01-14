from pswamp.gui.grid_view.dim_3d.layers.lines import LineLayer
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
from pswamp.utils.pmu_time_window import PMUTimeWindowOnline
import threading
import uuid
from pswamp.gui.grid_view.dim_3d.layers.frequency import Frequency3DLayerSettings



class LinesFreq(LineLayer):
    def __init__(self, parent, config, *args, **kwargs):
        self.config = config
        self.uuid = uuid.uuid4()
        super().__init__(parent, config, *args, **kwargs)
        
        self.pmu_tw = PMUTimeWindowOnline(n_samples=1, kafka_topic=config['topics']['pmudata'], io_kwargs=config["streaming"])
        self.pmu_tw.initialize()
        self.col_idx = self.get_col_idx()
        pmu_tw_thread = threading.Thread(target=self.pmu_tw.run, daemon=True)
        pmu_tw_thread.start()
        
        self.z_0 = 1
        self.z_scale = 3

        parent.update_funs[self.uuid] = self.update_z

    def get_col_idx(self):
        return self.pmu_tw.tw.get_col_idx(measurement='f')
    
    def update_z(self):
        freq = self.pmu_tw.tw.get_col(self.col_idx).flatten()
        z = self.z_0 + self.z_scale*(freq - 50)
        self.set_node_z(z)


class LinesFreqSettings(Frequency3DLayerSettings):
    pass
    # def slider_change(self, val):
    #     self.target_layer.z_scale = val/2


if __name__ == '__main__':
    from pswamp.gui.grid_view.dim_3d.base_plot_layers import GridBasePlot3D
    from pswamp import load_config
    import pswamp
    from pathlib import Path
    sample_dataset_path = Path(pswamp.__file__).parent / \
        'test_utils/sample_datasets/n44'

    config = load_config()
    print(config["streaming"])
    config['sld_data'] = {'line_data_path': sample_dataset_path/'sld.dxf'}
    config['model_data_path'] = sample_dataset_path/'model_data.json'

    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot3D(
        geo=False,
    )
    grid_plot.window.show()

    layer_instance = LinesFreq(grid_plot, config, geo=False)
    n_lines = layer_instance.n_lines

    layer_settings = LinesFreqSettings(layer_instance)
    layer_settings.show()

    app.exec()
