from PySide6 import QtGui, QtWidgets
import pyqtgraph as pg
from pswamp.visualization.countries_geo_data.read_geo_data import read_geo_data


class CountriesLayer:
    def __init__(self, parent, config, sld_id=None):
        self.config = config
        self.k = 2 if geo else 1
        self.plotWidget = parent.plotWidget
        countries_to_be_drawn = config['geo_data']['countries'] if 'geo_data' in config and 'countries' in config['geo_data'] else [
        ]
        geo_data = read_geo_data(countries_to_be_drawn)
        geo_data[:, 1] *= self.k
        self.geo_data = geo_data
        self.geo_lines = self.add_geo_lines(geo_data)
        self.plotWidget.addItem(self.geo_lines)

    def add_geo_lines(self, geo_data):
        geo_lines = pg.PlotCurveItem(
            geo_data[:, 0], geo_data[:, 1], connect='finite', pen=QtGui.QColor('gray')
        )
        return geo_lines

    def update_countries(self, countries=['Norway']):
        geo_data = read_geo_data(countries)
        self.geo_lines.setData(x=geo_data[:, 0], y=self.k*geo_data[:, 1])

    def remove_layer(self):
        self.plotWidget.removeItem(self.geo_lines)
        del self.geo_lines


class CountriesLayerSettings(QtWidgets.QWidget):
    def __init__(self, target_layer, *args, **kwargs) -> None:
        self.target_layer = target_layer
        super().__init__(*args, **kwargs)
        self.item_list = QtWidgets.QListWidget()
        self.item_list.addItems(['Norway', 'Sweden', 'Finland', 'Denmark'])
        self.item_list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)

        self.item_list.itemClicked.connect(self.onItemClicked)
        # self.item_list.mouseMoveEvent.connect(self.onItemClicked)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.item_list)

        self.done_button = QtWidgets.QPushButton('Done')
        self.done_button.clicked.connect(self.done_button_click)
        layout.addWidget(self.done_button)
        self.setLayout(layout)

    def done_button_click(self):
        self.close()

    def onItemClicked(self, item):
        selected_countries = [item.text()
                              for item in self.item_list.selectedItems()]
        self.target_layer.update_countries(selected_countries)

        
if __name__ == '__main__':
    from pswamp.gui.grid_view.dim_2d.base_plot_layers import GridBasePlot2D
    from pswamp import load_config

    config = load_config()
    
    app = QtWidgets.QApplication()
    grid_plot = GridBasePlot2D(
        geo=True,
    )
    grid_plot.window.show()

    layer_instance = CountriesLayer(grid_plot, config, geo=True)
    layer_settings = CountriesLayerSettings(layer_instance)
    layer_settings.show()

    app.exec()