import numpy as np
from pswamp.utils.misc import lookup_strings
from pswamp.utils.pypmu import PMUPhasorExtractor, PMUFreqExtractor
from pswamp.models.bus import read_model_data
import pandas as pd



def find_strings_containing_substring(strings_to_search, string_to_find):
    return np.flatnonzero(np.core.defchararray.find(strings_to_search, string_to_find) != -1)[0]



class Load:
    def __init__(self, config, meas_data, units=None):

        self.load_data = load_data = read_model_data(config, 'load')
        # trafo_data = read_model_data(model_data, 'transformers')
        self.bus_data = read_model_data(config, 'bus')
        
        units = load_data['name'] if units is None else units
            
        load_subset_idx = lookup_strings(units, load_data['name'])

        self.bus_idx = lookup_strings(load_data['bus'][load_subset_idx], self.bus_data['name'])

        phasor_extractor_kwargs = dict(
            stations=meas_data.get_station_name(),
            channels=meas_data.get_channel_names()
        )

        # self.freq_extractor = PMUFreqExtractor(
        #     wanted_stations=bus_data['name'][self.bus_idx].to_list(),
        #     stations=meas_data.get_station_name())

        self.current_phasor_extractor = PMUPhasorExtractor(
            wanted_stations=self.bus_data['name'][self.bus_idx].to_list(),
            wanted_channels=[[f'I[{unit}]'] for unit in units], **phasor_extractor_kwargs

        )
        self.v_phasor_extractor = PMUPhasorExtractor(
            wanted_stations=self.bus_data['name'][self.bus_idx].to_list(),
            wanted_channels=[['V']]*len(units),  **phasor_extractor_kwargs
        )

        # self.line_out_threshold = 1e-3


    def V(self, meas):
        V_polar = np.concatenate(self.v_phasor_extractor.get(meas.get_phasors()))
        return V_polar[:, 0]*np.exp(1j*V_polar[:, 1])
    
    # def freq(self, meas):
        # return self.freq_extractor.get(meas.get_freq())
    
    def I(self, meas):
        I_polar = np.concatenate(self.current_phasor_extractor.get(meas.get_phasors()))
        return I_polar[:, 0]*np.exp(1j*I_polar[:, 1])
    
    def S(self, meas):
        return np.sqrt(3)*self.V(meas)*np.conj(self.I(meas))
    
    def P(self, meas):
        return self.S(meas).real
    
    
    def Q(self, meas):
        return self.S(meas).imag
        
    # def disconnected(self, meas):
        # return abs(self.I(meas)) < self.line_out_threshold



if __name__ == '__main__':

    from pswamp import load_config
    import json
    config = load_config()
    # with open(config['model_data_path']) as file:
        # model_data = json.load(file)

    line_data = read_model_data(config, 'lines')
    trafo_data = read_model_data(config, 'transformers')
    load_data = read_model_data(config, 'loads')
    gen_data = read_model_data(config, 'generators')
    bus_data = read_model_data(config, 'buses')
    data = {
        'lines': {'Line': line_data},
        'trafos': {'Trafo': trafo_data},
        'loads': {'Load': load_data},
        'gen': {'GEN': gen_data},
        'buses': bus_data,
    }

    from topsrt.pmu_v2 import PMUPublisherV2 as PMUPublisher
    obj = type('', (), {'stations': None, 'ip': '', 'port': 0, 'pdc_id': 1, 'fs': 50})()
    PMUPublisher.initialize(obj, data)
    pmu_config_frame = obj.pmu.pmu.cfg2
    
    from pswamp.test_utils.csv_playback.data_frame_generator import DataFrameGenerator
    data_frame = DataFrameGenerator.generate_data_frame(pmu_config_frame)
    data_frame.cfg.get_ph_units()

    # units = ['L3000-3245-2', 'L3000-3115', 'L8500-8600']

    units = None  # line_data['name']
    # assert all([np.any(unit == line_data['name']) for unit in units])
    
    load_model = Load(config, pmu_config_frame, units)

    import timeit
    print(load_model.I(data_frame))
    print(load_model.V(data_frame))
    print(load_model.P(data_frame))
    # print(load_model.freq(data_frame))

    timeit.timeit(lambda: load_model.I(data_frame), number=50)