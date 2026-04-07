# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from PySide6 import QtWidgets
from pswamp.gui.grid_view.layer_select import LayerSelectTree
import pyqtgraph as pg


class LayerSettings(QtWidgets.QWidget):
    """Settings for grid view.

    Allows activating/deactivating visualization layers in the GridView, and
    seleecting the background color for the GridView.

    TODO: Change name to GridViewSettings?

    Args:
        config (dict): pswamp configuration.
        parent_widget (GridView2D or GridView3D): Grid view whose settings are adjusted.


    """
    def __init__(self, config, parent_widget, *args, **kwargs):
        super().__init__()
        
        background_color_text = QtWidgets.QLabel('Background color')
        background_color_button = pg.ColorButton()
        background_color_button.setColor((30, 63, 64))

        def change(background_color_button):
            parent_widget.change_background_color(background_color_button.color())

        background_color_button.sigColorChanging.connect(change)
        background_color_button.sigColorChanged.connect(change)

        self.layer_select = LayerSelectTree(config, parent_widget, *args, **kwargs)

        layout = QtWidgets.QGridLayout()
        layout.addWidget(background_color_text, 0, 0)
        layout.addWidget(background_color_button, 0, 1)
        layout.addWidget(self.layer_select, 1, 0, 1, 2)

        self.setLayout(layout)
        self.show()

        



def main():
    from pswamp.gui.grid_view.dim_2d.layers import CountriesLayer, CountriesLayerSettings, StaticLineDataLayer, PhasorPlotLayer, StationNamesLayer
    config = {}
    app = QtWidgets.QApplication()

    # grid_plot.add_layer()
    available_layers = {
        'Base layers': {
            'Countries': (CountriesLayer, CountriesLayerSettings),
            'Static line data': (StaticLineDataLayer, None),
            'Voltage phasors': (PhasorPlotLayer, None),
            'Station names': (StationNamesLayer, None),
        }
    }

    grid_plot = None

    layer_settings = LayerSettings(config, grid_plot, available_layers)

    app.exec()
    return app


if __name__ == '__main__':
    main()
