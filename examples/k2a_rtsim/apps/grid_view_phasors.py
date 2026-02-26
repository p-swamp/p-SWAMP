from pswamp.gui.grid_view.dim_2d.base_plot import GridBasePlot2D
from pswamp.gui.grid_view.dim_2d.layers.phasors import PhasorPlotLayer
from pswamp.utils.load_config import load_config
from PySide6 import QtWidgets


if __name__ == '__main__':
    config = load_config('..')
    app = QtWidgets.QApplication()
    grid_view = GridBasePlot2D()  # (config, activate_default_layers=False)
    phasor_layer = PhasorPlotLayer(grid_view, config, sld_id="1")
    grid_view.show()
    app.exec()