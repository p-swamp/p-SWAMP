# LICENSE HEADER MANAGED BY add-license-header
#
# Copyright 2026 NTNU/SINTEF/Statnett SF
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import sys, os
# sys.path.append(os.getcwd() + '\src')
import numpy as np
from pathlib import Path
from datetime import datetime
from pswamp.test_utils.csv_playback.data_reader import DataReader
import random
import time
from synchrophasor.frame import ConfigFrame2, DataFrame


class DataFrameGenerator(DataReader):
    def __init__(self, pmu_data_folder, case_name_hint='', pdc_id=1, publish_frequency=50, *args, **kwargs) -> None:
        super().__init__(pmu_data_folder, case_name_hint, *args, **kwargs)

        self.cfg2 = self.generate_cfg(
            publish_frequency=publish_frequency,
            station_names=self.stations,
            channel_names=self.channels,
            pdc_id=pdc_id,
            channel_types=self.channel_types,
            id_codes=self.pmu_ids
        )

    @staticmethod
    def generate_cfg(station_names, channel_names, pdc_id=1, channel_types=None, id_codes=None, publish_frequency=50):

        n_pmus = len(station_names)
        
        conf_kwargs = dict(
            pmu_id_code=pdc_id,  # PMU_ID
            time_base=1000000,  # TIME_BASE
            num_pmu=n_pmus,  # Number of PMUs included in recorded_pmu_data_raw frame
            data_format=(True, True, True, True),  # Data format - POLAR; PH - REAL; AN - REAL; FREQ - REAL;
            analog_num=0,  # Number of analog values
            digital_num=0,  # Number of digital status words
            an_units=[],  # (1, "pow")],  # Conversion factor for analog channels
            dig_units=[],  # (0x0000, 0xffff)],  # Mask words for digital status words
            f_nom=50,  # Nominal frequency
            cfg_count=1,  # Configuration change count
            data_rate=publish_frequency
        )

        other_channel_names = []

        if n_pmus == 1:
            n_phasors_per_pmu = len(channel_names[0])
            n_phasors = n_phasors_per_pmu
            conf_kwargs['id_code'] = id_codes[0] if id_codes is not None else 1
            conf_kwargs['station_name'] = station_names[0]  # 'PMU'
            conf_kwargs['ph_units'] = [(0, "v")]*n_phasors
            conf_kwargs['channel_names'] = channel_names[0] + other_channel_names
            conf_kwargs['phasor_num'] = n_phasors
        else:
            n_phasors_per_pmu = [len(channel_names_) for channel_names_ in channel_names]
            conf_kwargs['phasor_num'] = n_phasors_per_pmu
            if channel_types is not None:
                conf_kwargs['ph_units'] = [[(0, channel_type_) for channel_type_ in channel_type] for channel_type in channel_types]
            else:
                conf_kwargs['ph_units'] = [[(0, "v")]*n_phasors_per_pmu for n_phasors_per_pmu in n_phasors_per_pmu]  # Not correct?

            if id_codes is not None:
                conf_kwargs['id_code'] = id_codes
            else:
                conf_kwargs['id_code'] = list(range(1, n_pmus + 1))

            conf_kwargs['station_name'] = station_names
            conf_kwargs['channel_names'] = [channel_names_ + other_channel_names for channel_names_ in channel_names]
            for key in ['data_format', 'analog_num', 'digital_num', 'an_units', 'dig_units', 'f_nom', 'cfg_count']:
                conf_kwargs[key] = [conf_kwargs[key]] * n_pmus

        return ConfigFrame2(**conf_kwargs)
    
    def get_config_frame(self):
        return self.cfg2
    
    def get_next_data_frame(self):
        data_kwargs = self.get_next_row()
        if data_kwargs is None:
            return None
        return self.generate_data_frame(
            self.cfg2,
            **data_kwargs
        )


    @staticmethod
    def generate_data_frame(cfg2, stat=None, time_stamp=None, phasors=None, freq=None, dfreq=None, analog=None, digital=None):

        if time_stamp is None:
            time_stamp = time.time()

        n_pmus = cfg2.get_num_pmu()
        
        soc, frasec = [int(val) for val in format(time_stamp, '.6f').split(".")]
        frasec=(frasec, '+')

        default_status = ("ok", True, "timestamp", False, False, False, 0, "<10", 0)        
        if stat is None:
            stat = default_status if n_pmus == 1 else [default_status]*n_pmus        
        # phasors = None
        if phasors is None:
            if n_pmus == 1:
                phasors = [(random.uniform(215.0, 240.0), random.uniform(-np.pi, np.pi)) for _ in range(len(cfg2.get_channel_names()))]
            else:
                phasors = [[(random.uniform(215.0, 240.0), random.uniform(-np.pi, np.pi)) for _ in
                               range(len(channels))] for channels in cfg2.get_channel_names()]
                        
        if freq is None:
            freq = 0 if n_pmus == 1 else [0]*n_pmus

        if dfreq is None:
            dfreq = 0 if n_pmus == 1 else [0]*n_pmus
        
        if analog is None:
            analog=[] if n_pmus == 1 else [[]]*n_pmus
        
        if digital is None:
            digital=[] if n_pmus == 1 else [[]]*n_pmus
        
        # stat=("ok", True, "timestamp", False, False, False, 0, "<10", 0),
        data_frame = DataFrame(cfg2.get_id_code(), stat, phasors, list(freq), list(dfreq), list(analog), list(digital), cfg2, soc, frasec)
        return data_frame
