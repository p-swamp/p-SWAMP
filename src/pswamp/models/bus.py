import numpy as np
from pswamp.utils.misc import lookup_strings
from pswamp.utils.pypmu import PMUPhasorExtractor, PMUFreqExtractor
# from pswamp.models.reader import get_from_database
from pswamp.database import get_from_database
        
class Bus:
    def __init__(self, db_kwargs, meas_data, units=None):

        self.data = get_from_database(db_kwargs, 'bus')
        self.units = units = self.data['name'] if units is None else units


        self.bus_subset_idx = lookup_strings(units, self.data['name'])
        self.freq_extractor = PMUFreqExtractor(
            self.data['name'][self.bus_subset_idx].to_numpy(),
            meas_data.cfg.get_station_name())
        
        self.v_phasor_extractor = PMUPhasorExtractor(
            wanted_stations=self.data['name'][self.bus_subset_idx].to_list(),
            wanted_channels=[['V']]*len(units),
            dataframe=meas_data)
        
        self.v_max = self.data["v_max"].to_numpy() if "v_max" in self.data else 1.1
        self.v_min = self.data["v_min"].to_numpy() if "v_min" in self.data else 0.9
        self.V_n = self.data["V_n"].to_numpy()

    def V(self, meas):
        # Voltage [V]
        V_polar = np.concatenate(self.v_phasor_extractor.get(meas.get_phasors()))
        return V_polar[:, 0]*np.exp(1j*V_polar[:, 1])
    
    def v(self, meas):
        # Voltage [p.u.]
        return self.V(meas)/self.V_n[self.bus_subset_idx]
    
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

    line_data = get_from_database(config, 'line')
    trafo_data = get_from_database(config, 'trafo')
    
    # copy_bus = model_data['buses'][-1].copy()
    # copy_bus[0] = '8701'
    # model_data['buses'].append(copy_bus)
    bus_data = get_from_database(config, 'bus')
    # len(bus_data)
    # popped_bus = model_data['buses'].pop()
    # bus_data_mod = get_from_database(model_data, 'buses')
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