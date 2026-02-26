from PySide6 import QtWidgets
import sys
from pswamp.gui.grid_view.dim_2d.base_plot import GridBasePlot2D
import pswamp.gui.grid_view.dim_2d.layers as lrs
from pswamp.gui.grid_view.layer_settings import LayerSettings
from pswamp.utils.load_config import load_config


class GridBasePlot2DLayers(GridBasePlot2D):
    def __init__(self, config, activate_default_layers=True, sld_id=None, *args, **kwargs):
        try:
            background_color = config['graphics']['background_color']
        except KeyError:
            background_color = None
        
        super().__init__(
            *args,
            background_color=background_color,
            **kwargs)
        # layers_edit_btn = QtWidgets.QPushButton("Layers")
        # layers_edit_btn.clicked.connect(self.onLayersEditClicked)
        # proxy = QtWidgets.QGraphicsProxyWidget()
        # proxy.setWidget(layers_edit_btn)
        # self.window.addItem(proxy)
        self.sld_id = sld_id
        sld_spec = config["single_line_diagrams"]
        self.geo = (
            sld_spec[sld_id]["geo"]
            if sld_id is not None and "geo" in sld_spec[sld_id]
            else False
        )

        available_layers = {
            "Base layers": {
                # 'Countries': (CountriesLayer, CountriesLayerSettings),
                # 'Static line data': (lrs.StaticLineDataLayer, lrs.StaticLineDataLayerSettings),
                # 'Static line data (oim)': (lrs.StaticLineDataLayer_v0, lrs.StaticLineDataLayerSettings),
                "Bus names": (lrs.BusNamesLayer, None),
                "Buses": (lrs.BusesLayer, None),
                "Lines": (lrs.LineLayer, None),
                # 'PMUs': (lrs.PMULayer, None),
            },
            "Other layers": {
                "Frequency heat map": (lrs.FrequencyHeatMap, None),
                "Voltage phasors": (lrs.PhasorPlotLayer, None),
            },
        }
        # default_layers = ['Static line data', 'Static line data (oim)', 'Station names', 'Buses']
        default_layers = [
            # "Static line data",
            # "Static line data (oim)",
            "Bus names",
            "Buses",
        ]
        if self.geo:
            available_layers['Base layers'].update(
                {'Countries': (lrs.CountriesLayer, lrs.CountriesLayerSettings)}
            )
            default_layers.append('Countries')
            


        self.layer_settings = LayerSettings(config, self, available_layers)
        self.layer_settings.layer_select.topLevelItem(0).setExpanded(True)

        if activate_default_layers:
            for child_layer in available_layers['Base layers']:
                if child_layer in default_layers:
                    self.layer_settings.layer_select.show_layer('Base layers', child_layer)
        # self.layer_select.hide()

    #     self.center_camera_position(config)

    # def center_camera_position(self, config):
    #     _, bus_coords = load_bus_coords_for_current_stations(config, geo=self.geo)
    #     k = 2 if self.geo else 1
    #     bus_coords[:, 1] *= k
        
    #     self.plotWidget.setXRange(
    #         np.nanmin(bus_coords[:, 0]), np.nanmax(bus_coords[:, 0], padding=0)
    #     )
    #     self.plotWidget.setYRange(
    #         np.nanmin(bus_coords[:, 1]), np.nanmax(bus_coords[:, 1], padding = 0)
    #     )
        

    # def onLayersEditClicked(self):
        # self.layer_select.show()

def main():
    config=load_config()
    config["streaming"]["bootstrap_servers"] = "localhost:40011"
    config['graphics'] = {
        'background_color': [255, 255, 255],
        'gl_mode': 'translucent'}

    app = QtWidgets.QApplication(sys.argv)
    grid_plot = GridBasePlot2DLayers(
        config=config,
        # update_freq=25,
        # k=2,
        activate_default_layers=False
    )
    grid_plot.window.show()    
    app.exec()   
    return app


if __name__ == '__main__':
    main()