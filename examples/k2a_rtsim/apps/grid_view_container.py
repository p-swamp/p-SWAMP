from watools.gui.grid_view.grid_view_container import GridViewContainer
from watools.utils.load_config import load_config
from PySide6 import QtWidgets


if __name__ == '__main__':
    config = load_config('..')
    app = QtWidgets.QApplication()
    grid_view = GridViewContainer(config, activate_default_layers=False)
    grid_view.show()
    app.exec()