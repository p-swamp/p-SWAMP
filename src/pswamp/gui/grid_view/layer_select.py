# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from PySide6 import QtCore, QtWidgets
from pswamp.gui.grid_view.exceptions import LayerFailedException




"""Obtained from https://stackoverflow.com/questions/23074025/how-to-check-state-of-qtreewidget-item"""
def handle(self, item, column):
    """Not sure if this is used."""
    self.treeWidget.blockSignals(True)
    if item.checkState(column) == QtCore.Qt.Checked:
        self.handleChecked(item, column)
    elif item.checkState(column) == QtCore.Qt.Unchecked:
        self.handleUnchecked(item, column)
    self.treeWidget.blockSignals(False)

"""Obtained from https://stackoverflow.com/questions/23074025/how-to-check-state-of-qtreewidget-item"""
class TreeWidgetItem(QtWidgets.QTreeWidgetItem):
    """Modified QTreeWidgetItem, to be able to see which items are checked
    """
    def setData(self, column, role, value):
        state = self.checkState(column)
        QtWidgets.QTreeWidgetItem.setData(self, column, role, value)
        if (role == QtCore.Qt.CheckStateRole and state != self.checkState(column)):
            treewidget = self.treeWidget()
            if treewidget is not None:
                treewidget.itemChecked.emit(self, column)


class LayerSelectTree(QtWidgets.QTreeWidget):
    """Tree with layers that can be selected.

    Layers are organized in categories. Doubleclicking a layer causes a pop-up
    with settings for that layer (if available).

    TODO: Remove *args from argument list (not used).

    Args:
        config (dict): pswamp configuration
        parent_widget
    """
    itemChecked = QtCore.Signal(object, int)

    def __init__(self, config, parent_widget, layers_data, *args):
        """
        Constructor. Channel names is specified as list of list of channel names, where each sublist corresponds to a
        station.
        Args:
            station_names: List of Station names
            channel_names: List of list of channel names
            *args:
        """
        self.config = config
        self.parent_widget = parent_widget
        super().__init__()
        # app = QApplication(sys.argv)

        self.setHeaderLabel('')
        headerItem = QtWidgets.QTreeWidgetItem()
        headerItem.setText(0, '')
        item = QtWidgets.QTreeWidgetItem()
        self.layers_data = layers_data
        self.active_layer_instances = {}

        self.itemChecked.connect(self.onItemChecked)
        self.itemDoubleClicked.connect(self.onItemDoubleClicked)

        self.layer_to_idx = {}
        for parent_layer_name, child_layers in layers_data.items():
            self.layer_to_idx[parent_layer_name] = {}
            parent = TreeWidgetItem(self)
            parent.setText(0, parent_layer_name)
            for layer_name, (layer_class, layer_settings_class) in child_layers.items():
                child = TreeWidgetItem(parent)
                child.setFlags(child.flags() | QtCore.Qt.ItemIsUserCheckable)
                child.setText(0, layer_name)
                child.setCheckState(0, QtCore.Qt.Unchecked)
                parent.indexOfChild(child)
                self.layer_to_idx[parent_layer_name][layer_name] = child

            # k_station += 1
        self.show()

    def show_layer(self, parent_layer, child_layer):
        check_box = self.layer_to_idx[parent_layer][child_layer]
        check_box.setCheckState(0, QtCore.Qt.Checked)

    @QtCore.Slot(QtWidgets.QTreeWidgetItem, int)
    def onItemChecked(self, it, col):
        parent = it.parent()
        if parent is None:
            return

        child_layer = it.text(col)
        parent_layer = parent.text(col)
        # print(parent_layer, child_layer)

        if parent_layer not in self.active_layer_instances:
            self.active_layer_instances[parent_layer] = {}

        if it.checkState(col).value == 2:  # Box was checked
            # self.show_layer(parent_layer, child_layer)
            layer_class, layer_settings_dialogue_class = self.layers_data[parent_layer][child_layer]          
            try:
                new_layer_instance = layer_class(self.parent_widget, self.config, sld_id=self.parent_widget.sld_id)
                self.active_layer_instances[parent_layer][child_layer] = new_layer_instance
            except LayerFailedException:
                print(f'Could not instantiate layer: {parent_layer}, {child_layer}')
                it.setCheckState(0, QtCore.Qt.Unchecked)
                
        elif child_layer in self.active_layer_instances[parent_layer]:  # elif it.checkState(col).value == 0:  # Box was unchecked
            self.active_layer_instances[parent_layer][child_layer].remove_layer()
            del self.active_layer_instances[parent_layer][child_layer]

    @QtCore.Slot(QtWidgets.QTreeWidgetItem, int)
    def onItemDoubleClicked(self, it, col):
        # print(it, col, it.text(col))
        parent = it.parent()
        if parent is None:
            return

        child_layer = it.text(col)
        parent_layer = parent.text(col)
        print(parent_layer, child_layer)

        layer_class, layer_settings_dialogue_class = self.layers_data[parent_layer][child_layer]
        layer_exists = parent_layer in self.active_layer_instances and child_layer in self.active_layer_instances[
            parent_layer]
        if layer_exists and layer_settings_dialogue_class is not None:
            layer_instance = self.active_layer_instances[parent_layer][child_layer]
            self.active_dialogue = layer_settings_dialogue_class(
                layer_instance)
            self.active_dialogue.show()


def main():
    from pswamp.gui.grid_view.dim_2d.layers import CountriesLayer,\
        CountriesLayerSettings, PhasorPlotLayer#,\
        # StationNamesLayer, StaticLineDataLayer
    
    config = {}
    app = QtWidgets.QApplication()

    # grid_plot.add_layer()
    available_layers = {
        'Base layers': {
            'Countries': (CountriesLayer, CountriesLayerSettings),
            # 'Static line data': (StaticLineDataLayer, None),
            'Voltage phasors': (PhasorPlotLayer, None),
            # 'Station names': (StationNamesLayer, None),
        }
    }

    grid_plot = None

    layer_select = LayerSelectTree(config, grid_plot, available_layers)

    app.exec()
    return app


if __name__ == '__main__':
    main()
