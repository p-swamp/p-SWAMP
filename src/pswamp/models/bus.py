import numpy as np
from pswamp.utils.misc import lookup_strings
from pswamp.utils.pypmu import PMUPhasorExtractor, PMUFreqExtractor
from pswamp.models.reader import read_model_data
        
class Bus:
    def __init__(self, config, meas_data, units=None):

        self.bus_data = read_model_data(config, 'bus')
        self.units = units = self.bus_data['name'] if units is None else units


        self.bus_subset_idx = lookup_strings(units, self.bus_data['name'])
        self.freq_extractor = PMUFreqExtractor(
            self.bus_data['name'][self.bus_subset_idx].to_numpy(),
            meas_data.get_station_name())
        
        self.v_phasor_extractor = PMUPhasorExtractor(
            wanted_stations=self.bus_data['name'][self.bus_subset_idx].to_list(),
            wanted_channels=[['V']]*len(units),
            stations=meas_data.get_station_name(),
            channels=meas_data.get_channel_names())
        
        self.v_max = self.bus_data["v_max"] if "v_max" in self.bus_data else 1.1
        self.v_min = self.bus_data["v_min"] if "v_min" in self.bus_data else 0.9

    def V(self, meas):
        # Voltage [V]
        V_polar = np.concatenate(self.v_phasor_extractor.get(meas.get_phasors()))
        return V_polar[:, 0]*np.exp(1j*V_polar[:, 1])
    
    def v(self, meas):
        # Voltage [p.u.]
        return self.V(meas)/self.bus_data['V_n'].to_numpy()[self.bus_subset_idx]
    
    def overvoltage(self, meas):
        return abs(self.v(meas)) > self.v_max

    def undervoltage(self, meas):
        return abs(self.v(meas)) < self.v_min
    
    def freq(self, meas):
        # Frequency
        return self.freq_extractor.get(meas.get_freq())
    
    def dfreq(self, meas):
        # ROCOF
        return self.freq_extractor.get(meas.get_dfreq())


if __name__ == '__main__':

    from pswamp import load_config
    config = load_config()

    line_data = read_model_data(config, 'line')
    trafo_data = read_model_data(config, 'trafo')
    
    # copy_bus = model_data['buses'][-1].copy()
    # copy_bus[0] = '8701'
    # model_data['buses'].append(copy_bus)
    bus_data = read_model_data(config, 'bus')
    # len(bus_data)
    # popped_bus = model_data['buses'].pop()
    # bus_data_mod = read_model_data(model_data, 'buses')
    # len(bus_data_mod)
    # model_data['buses'].append(popped_bus)

    
    from topsrt.pmu_currents_freq import PMUPublisherCurrentsFreq
    obj = type('', (), {'stations': None, 'ip': '', 'port': 0, 'pdc_id': 1, 'fs': 50})()
    PMUPublisherCurrentsFreq.initialize(obj, [bus_data, line_data, trafo_data])
    pmu_config_frame = obj.pmu.pmu.cfg2
    
    from pswamp.test_utils.csv_playback.data_frame_generator import DataFrameGenerator
    data_frame = DataFrameGenerator.generate_data_frame(pmu_config_frame)
    data_frame.cfg.get_ph_units()

    # units = ['L3000-3245-2', 'L3000-3115', 'L8500-8600']
    units = bus_data['name']
    # assert all([np.any(unit == line_data['name']) for unit in units])
    
    bus_model = Bus(config, pmu_config_frame, units)

    import timeit
    print(bus_model.V(data_frame))
    print(bus_model.v(data_frame))
    print(bus_model.freq(data_frame))

    timeit.timeit(lambda: bus_model.V(data_frame), number=50)