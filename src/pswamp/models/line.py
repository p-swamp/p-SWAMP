import numpy as np
from pswamp.utils.misc import lookup_strings
from pswamp.utils.pypmu import PMUPhasorExtractor, PMUFreqExtractor
from pswamp.models.bus import read_model_data
import pandas as pd



def find_strings_containing_substring(strings_to_search, string_to_find):
    return np.flatnonzero(np.core.defchararray.find(strings_to_search, string_to_find) != -1)[0]



class Line:
    def __init__(self, config, meas_data, units=None):

        line_data = read_model_data(config, 'line')
        # trafo_data = read_model_data(model_data, 'transformers')
        bus_data = read_model_data(config, 'bus')
        
        self.units = units = line_data['name'] if units is None else units
            
        line_subset_idx = lookup_strings(units, line_data['name'])

        self.from_bus_idx = lookup_strings(line_data['from_bus'][line_subset_idx], bus_data['name'])
        self.to_bus_idx = lookup_strings(line_data['to_bus'][line_subset_idx], bus_data['name'])

        phasor_extractor_kwargs = dict(
            stations=meas_data.get_station_name(),
            channels=meas_data.get_channel_names()
        )

        self.freq_from_extractor = PMUFreqExtractor(
            wanted_stations=bus_data['name'][self.from_bus_idx].to_list(),
            stations=meas_data.get_station_name())
        
        self.freq_to_extractor = PMUFreqExtractor(
            wanted_stations=bus_data['name'][self.to_bus_idx].to_list(),
            stations=meas_data.get_station_name())

        self.current_phasor_extractor_from = PMUPhasorExtractor(
            wanted_stations=bus_data['name'][self.from_bus_idx].to_list(),
            wanted_channels=[[f'I[{unit}]'] for unit in units], **phasor_extractor_kwargs
        )
        self.current_phasor_extractor_to = PMUPhasorExtractor(
            wanted_stations=bus_data['name'][self.to_bus_idx].to_list(),
            wanted_channels=[[f'I[{unit}]'] for unit in units], **phasor_extractor_kwargs
        )
        self.v_from_phasor_extractor = PMUPhasorExtractor(
            wanted_stations=bus_data['name'][self.from_bus_idx].to_list(),
            wanted_channels=[['V']]*len(units),  **phasor_extractor_kwargs
        )
        self.v_to_phasor_extractor = PMUPhasorExtractor(
            wanted_stations=bus_data['name'][self.to_bus_idx].to_list(),
            wanted_channels=[['V']]*len(units), **phasor_extractor_kwargs
        )

        self.line_out_threshold = 1e-3

        ld = line_data.iloc[line_subset_idx]
        bd = bus_data
        
        self.S_n = ld['S_n'].to_numpy(float) if 'S_n' in ld.columns else np.inf
        self.S_n[self.S_n==0] = np.inf
        
        self.V_n = ld['V_n'].to_numpy(float) if 'V_n' in ld.columns else np.nan
        self.V_n[self.V_n==0] = bd['V_n'][self.from_bus_idx]
        
        self.I_n = self.S_n/(np.sqrt(3)*self.V_n)


    def V_from(self, meas):
        V_polar = np.concatenate(self.v_from_phasor_extractor.get(meas.get_phasors()))
        return V_polar[:, 0]*np.exp(1j*V_polar[:, 1])

    def V_to(self, meas):
        V_polar = np.concatenate(self.v_to_phasor_extractor.get(meas.get_phasors()))
        return V_polar[:, 0]*np.exp(1j*V_polar[:, 1])
    
    def freq_from(self, meas):
        return self.freq_from_extractor.get(meas.get_freq())
    
    def freq_to(self, meas):
        return self.freq_to_extractor.get(meas.get_freq())
    
    def I_from(self, meas):
        I_polar = np.concatenate(self.current_phasor_extractor_from.get(meas.get_phasors()))
        return I_polar[:, 0]*np.exp(1j*I_polar[:, 1])
    
    def I_to(self, meas):
        I_polar = np.concatenate(self.current_phasor_extractor_to.get(meas.get_phasors()))
        return I_polar[:, 0]*np.exp(1j*I_polar[:, 1])
    
    def S_from(self, meas):
        return np.sqrt(3)*self.V_from(meas)*np.conj(self.I_from(meas))
    
    def S_to(self, meas):
        return np.sqrt(3)*self.V_to(meas)*np.conj(self.I_to(meas))
    
    def P_from(self, meas):
        return self.S_from(meas).real
    
    def P_to(self, meas):
        return self.S_to(meas).real
    
    def Q_from(self, meas):
        return self.S_from(meas).imag
    
    def Q_to(self, meas):
        return self.S_to(meas).imag
        
    def disconnected(self, meas):
        # voltages_unequal = np.abs(
            # self.V_from(meas) - self.V_to(meas)) > self.voltages_equal_threshold  
        current_zero = abs(self.I_from(meas)) < self.line_out_threshold
        return current_zero  # *voltages_unequal


    def connectable(self, meas):
        angle_difference = (np.angle(self.V_from(meas)) - np.angle(self.V_to(meas)))%(2*np.pi)
        return (abs(angle_difference) < 30/180*np.pi)*self.disconnected(meas)


if __name__ == '__main__':

    from pswamp import load_config
    import json
    config = load_config()
    # with open(config['model_data_path']) as file:
        # model_data = json.load(file)

    line_data = read_model_data(config, 'line')
    trafo_data = read_model_data(config, 'trafo')
    bus_data = read_model_data(config, 'bus')

    from topsrt.pmu_currents_freq import PMUPublisherCurrentsFreq
    obj = type('', (), {'stations': None, 'ip': '', 'port': 0, 'pdc_id': 1, 'fs': 50})()
    PMUPublisherCurrentsFreq.initialize(obj, [bus_data, line_data, trafo_data])
    pmu_config_frame = obj.pmu.pmu.cfg2
    
    from pswamp.test_utils.csv_playback.data_frame_generator import DataFrameGenerator
    data_frame = DataFrameGenerator.generate_data_frame(pmu_config_frame)
    data_frame.cfg.get_ph_units()

    units = ['L3000-3245-2', 'L3000-3115', 'L8500-8600']
    # units = line_data['name']
    assert all([np.any(unit == line_data['name']) for unit in units])
    
    line_model = Line(config, pmu_config_frame, units)

    import timeit
    print(line_model.I_from(data_frame))
    print(line_model.I_to(data_frame))

    print(line_model.V_from(data_frame))
    print(line_model.V_to(data_frame))

    print(line_model.freq_from(data_frame))
    print(line_model.freq_to(data_frame))

    print(line_model.P_from(data_frame))
    print(line_model.P_to(data_frame))
    
    print(line_model.I_n)

    timeit.timeit(lambda: line_model.I_from(data_frame), number=50)