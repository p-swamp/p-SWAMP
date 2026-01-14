from PySide6 import QtWidgets
import sys
from pswamp.gui.grid_view.dim_3d.base_plot import GridBasePlot3D
from pswamp.gui.grid_view.dim_3d.layers import *
from pswamp.gui.grid_view.layer_settings import LayerSettings
from pswamp.utils.load_config import load_config


class GridBasePlot3DLayers(GridBasePlot3D):
    def __init__(self, config, activate_default_layers=True, geo=True, *args, **kwargs):

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
        self.geo = geo

        available_layers = {
            'Base layers': {
                # 'Countries': (CountriesLayer, CountriesLayerSettings),
                'Static line data': (StaticLineDataLayer, StaticLineDataLayerSettings),
                'Static line data (oim)': (StaticLineDataLayer_v0, StaticLineDataLayerSettings),
                'Station names': (StationNamesLayer, None),
                'Buses': (BusesLayer, None),
            },
            'Other layers':{
                'Voltage phasors': (PhasorPlotLayer, None),
                'Voltage phasors (fast)': (PhasorPlotFastLayer, None),
                'Bus frequency': (Frequency3DLayer, Frequency3DLayerSettings),
                'Bus voltage': (Voltage3DLayer, Voltage3DLayerSettings),
                'Voltage Stability': (VoltageStability, None),
                'Islanding': (IslandingOnline, None),
                'Grid events': (GridEvents, None),
                'Dynamic lines, frequency': (LinesFreq, LinesFreqSettings),
                'Line outages': (LineOutages, None),
            }
        }
        default_layers = ['Static line data', 'Static line data (oim)', 'Station names', 'Buses']
        if self.geo:
            available_layers['Base layers'].update(
                {'Countries': (CountriesLayer, CountriesLayerSettings)}
            )
            default_layers.append('Countries')

        self.layer_settings = LayerSettings(config, self, available_layers)
        self.layer_settings.layer_select.topLevelItem(0).setExpanded(True)
        
        if activate_default_layers:
            for child_layer in available_layers['Base layers']:
                if child_layer in default_layers:
                    self.layer_settings.layer_select.show_layer('Base layers', child_layer) 
        # self.layer_select.hide()
        
            self.center_camera_position(config)

        
    def set_non_base_layers_visibility(self, show=False):
        for layer_category, layers in self.layer_settings.layer_select.active_layer_instances.items():
            if layer_category == 'Base layers':
                continue
            for layer_name, layer in layers.items():
                if hasattr(layer, 'show') and hasattr(layer, 'hide'):
                    layer.show() if show else layer.hide()

    def set_layer_visibility(self, category, layer, show=False):
        layer_instances = self.layer_settings.layer_select.active_layer_instances
        if not (category in layer_instances and layer in layer_instances[category]):
            return
        
        layer_instance = layer_instances[category][layer]
        if not (hasattr(layer_instance, 'show') and hasattr(layer_instance, 'hide')):
            return
        
        layer_instance.show() if show else layer_instance.hide()

            
    
    def center_camera_position(self, config):
        try:
            _, bus_coords = load_bus_coords_for_current_stations(config, geo=self.geo)
        except ConnectionRefusedError:
            print('None')
            return
        
        k = 2 if self.geo else 1
        bus_coords[:, 1] *= k

        x_center = np.mean([np.nanmin(bus_coords[:, 0]), np.nanmax(bus_coords[:, 0])])
        y_center = np.mean([np.nanmin(bus_coords[:, 1]), np.nanmax(bus_coords[:, 1])])

        self.plotWidget.setCameraPosition(
            pos=QtGui.QVector3D(
                x_center, y_center, 0
            ),
            distance=40,
            elevation=25,
            azimuth=-90,
        )

    # def onLayersEditClicked(self):
        # self.layer_select.show()
        

def main():
    app = QtWidgets.QApplication(sys.argv)
    config = load_config()
    config["streaming"]['bootstrap_servers'] = 'localhost:40011'
    # config['graphics'] = {
        # 'background_color': [255, 255, 255],
        # 'gl_mode': 'translucent'}
    
    from pathlib import Path
    import pswamp
    sample_dataset_path = Path(pswamp.__file__).parent/'test_utils/sample_datasets/n44'
    # config['sld_data'] = {'line_data_path': sample_dataset_path/'sld.dxf'}
    # config['geo_data'] = {'countries': ['Norway', 'Sweden', 'Denmark', 'Finland'], 'line_data_path': sample_dataset_path/'sld_geo.dxf'}
    # config['model_data_path'] = sample_dataset_path/'model_data.json'

    grid_plot = GridBasePlot3DLayers(
        config=config,
        # update_freq=25,
        geo=True,
        activate_default_layers=False
    )
    grid_plot.window.show()    
    app.exec()   
    return app


if __name__ == '__main__':
    main()