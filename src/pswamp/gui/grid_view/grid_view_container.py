
from PySide6.QtWidgets import QDialog, QGridLayout, QLineEdit, QLabel, QTabBar,\
    QRadioButton, QButtonGroup, QPushButton, QWidget, QToolButton, QComboBox
from pswamp.gui.grid_view.tab_widget import QTabWidgetPlus
from pswamp.gui.grid_view.dim_2d.base_plot_layers import GridBasePlot2DLayers
from pswamp.gui.grid_view.dim_3d.base_plot_layers import GridBasePlot3DLayers


from pswamp.test_utils.sample_datasets.minimal_case import create_minimal_test_case
import pyqtgraph as pg
from nqkafka.utils import stop_server


class NewViewOpts(QDialog):
    """Dialog with options for a new grid view.

    This is shown when a new grid view is to be added to the grid view
    container. The user selects 2D or 3D view, and whether to use geographic
    (geo) or single-line diagram (sld) representation.

    TODO: geo/sld is a bit confusing, since both variants show single-line
    diagrams. Should be changed (available variants could instead be specified
    in config.toml, and show up with similar names here).
    
    Args:
        show_sld (bool): Determines whether buttons for SLD view are shown.
    """
    def __init__(self, sld_list=[]):
        super().__init__()
        layout = QGridLayout()

        text_label = QLabel('View name')
        layout.addWidget(text_label, 0, 0, 1, 2)
        self.text_input = QLineEdit()
        layout.addWidget(self.text_input, 1, 0, 1, 2)

        button_group_1 = QButtonGroup(self)
        button_group_2 = QButtonGroup(self)

        text_label = QLabel('Settings')
        layout.addWidget(text_label, 2, 0, 1, 2)

        select_2d = QRadioButton('2D')
        select_2d.dimension = "2D"
        # select_2d.toggled.connect(self.onClicked)
        layout.addWidget(select_2d, 3, 0)

        select_3d = QRadioButton("3D")
        select_3d.setChecked(True)
        select_3d.dimension = "3D"
        # select_3d.toggled.connect(self.onClicked)
        layout.addWidget(select_3d, 4, 0)

        button_group_1.addButton(select_2d)
        button_group_1.addButton(select_3d)

        # select_geo = QRadioButton('Geo')
        # select_geo.dimension = "Geo"
        # # select_geo.toggled.connect(self.onClicked)
        # layout.addWidget(select_geo, 3, 1)

        
        # select_sld = QRadioButton("SLD")
        # select_sld.setChecked(True)
        # select_sld.dimension = "SLD"
        # # select_sld.toggled.connect(self.onClicked)
        # layout.addWidget(select_sld, 4, 1)

        # button_group_2.addButton(select_geo)
        # button_group_2.addButton(select_sld)
        select_sld = QComboBox()
        [select_sld.addItems([item]) for item in sld_list]
        layout.addWidget(select_sld, 3, 1)

        # if not show_sld:
        #     select_sld.hide()
        #     select_sld.setChecked(False)
        #     select_geo.setChecked(True)

        self.done_button = QPushButton('Done')
        self.done_button.clicked.connect(self.submitclose)
        layout.addWidget(self.done_button, 5, 0, 1, 2)

        self.select_2d = select_2d
        self.select_3d = select_3d
        self.select_sld = select_sld
        # self.select_geo = select_geo
        # self.select_sld = select_sld

        self.data = {}
        self.canceled = True

        self.setLayout(layout)

    def submitclose(self):
        """Close the dialog and create the new view."""
        # do whatever you need with self.roiGroups
        self.canceled = False
        self.data = {
            "view_name": self.text_input.text(),
            "3D": self.select_3d.isChecked(),
            "SLD": self.select_sld.currentText(),
        }
        self.accept()

    def submitcancel(self):
        """Close the dialog and don't create the new view."""
        # do whatever you need with self.roiGroups
        self.canceled = True
        self.accept()


class GridViewContainer(QTabWidgetPlus):
    """Container for multiple grid views.
    
    This widget holds multiple grid views as tabs. New views can be defined
    based on user input (2D/3D, geo/sld). When double clicking the tab for a
    view, the settings for the view can be modified (e.g., activate/deactivate
    visualization layers).

    TODO: Check if *args, **kwargs are used. Remove if not.

    Args:
        config (dict): pswamp configuration
        activate_default_layers (bool): Activate default layers or not.
    """
    new_tab_dialog_type=NewViewOpts

    def __init__(self, config, activate_default_layers=True, *args, **kwargs):
        self.config = config
        self.activate_default_layers = activate_default_layers
        
        self.tabname_to_widget_lookup = {}
        self.views = self.tabname_to_widget_lookup
        super().__init__(*args, **kwargs)
        self.tabBarDoubleClicked.connect(self.openTabDialog)

    def openTabDialog(self, tab_idx):
        """Open grid view settings dialog.
        
        Args:
            tab_idx (int): Index of the clicked tab.
        """
        layer_select_widget = self.tabname_to_widget_lookup[self.tabText(tab_idx)].layer_settings
        layer_select_widget.show()
        # layer_select_widget.setWindowFlags(QtCore.Qt.Popup)
        # layer_select_widget.setAttribute(QtCore.Qt.WA_QuitOnClose)
        layer_select_widget.raise_()
        # layer_select_widget.focusOutEvent.connect(lambda: layer_select_widget.hide())
    
    def _build_tabs(self):
        """Defines how new tabs are created."""
        first_tab_name = "View 1"
        first_sld_id = next(iter(self.config["single_line_diagrams"].keys()))
        # first_plot_is_geo = first_sld_data["geo"] if "geo" in first_sld_data else False
        first_tab_widget = GridBasePlot3DLayers(
            self.config,
            activate_default_layers=self.activate_default_layers,
            sld_id=first_sld_id,
        )
        first_tab_widget.layer_settings.hide()
        self.insertTab(0, first_tab_widget.window, first_tab_name)
        self.tabname_to_widget_lookup[first_tab_name] = first_tab_widget
        self.insertTab(1, QWidget(), '')
        nb = self.new_btn = QToolButton()
        nb.setText('+')
        nb.setAutoRaise(True)
        nb.clicked.connect(self.new_tab)
        self.tabBar().setTabButton(1, QTabBar.RightSide, nb)

    def new_tab(self):
        """Add new tab, store which widget the tab points to."""
        sld_data = self.config["single_line_diagrams"]
        sld_list = sld_data.keys()
        new_view_dialog = self.new_tab_dialog_type(sld_list=sld_list)
        new_view_dialog.exec()
        new_view_spec = new_view_dialog.data

        if not new_view_dialog.canceled:
            self.n_tabs += 1
            index = self.count() - 1
            # "View %d" % (self.n_tabs))
            grid_base_plot_class = GridBasePlot3DLayers if new_view_spec['3D'] else GridBasePlot2DLayers
            # k = 1 if new_view_spec['SLD'] else 2
            # if not new_view_spec['3D']:
            new_widget = grid_base_plot_class(
                self.config, activate_default_layers=self.activate_default_layers, sld_id=new_view_spec['SLD'])
            # else:
                # new_widget = GridBasePlot3DLayers(self.config, activate_default_layers=self.activate_default_layers)
            
            self.insertTab(index, new_widget.window, new_view_dialog.data['view_name'])
            self.tabname_to_widget_lookup[new_view_dialog.data['view_name']] = new_widget
            new_widget.layer_settings.hide()
            
            self.setCurrentIndex(index)


# if __name__ == '__main__':

#     app = QApplication(sys.argv)

#     # new_view_opts = NewViewOpts()
#     # new_view_opts.exec()
#     # print(new_view_opts.data)
#     from pswamp.utils.load_config import load_config
#     config = load_config()
#     config["single_line_diagrams"] = {"sld1": {"geo": True}, "sld2": {}}
#     tabs = GridViewContainer(config, False)
#     tabs.show()

#     app.exec()




if __name__ == "__main__":

    config, con, pmu = create_minimal_test_case()
    print(config)
    
    app = pg.mkQApp()
    tabs = GridViewContainer(config, False)
    tabs.show()
    

    app.exec()
    stop_server(config["streaming"]["bootstrap_servers"])