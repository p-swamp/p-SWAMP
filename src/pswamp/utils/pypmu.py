import numpy as np
from pswamp.utils.misc import lookup_strings
from pswamp.utils.time_window_labeled import Indexer


class PMUDecoder:
    def __init__(
        self,
        channel_selection=None,
        channel_selection_idx=None,
        substitute_zero_freq_with_nan=True,
    ):

        self.channel_selection = channel_selection
        if channel_selection_idx is not None:
            self.channel_selection = None
        self.channel_selection_idx = (
            np.array(channel_selection_idx)
            if channel_selection_idx is not None
            else slice(None)
        )

        self.substitute_zero_freq_with_nan = substitute_zero_freq_with_nan
        self.data_dtype = float

    def get_time_stamp(self, data_frame):
        return data_frame.get_time_stamp()

    def get_data_rate(self, sample_data_frame):
        return sample_data_frame.cfg.get_data_rate()

    def generate_header(self, sample_data_frame=None, config_frame=None):
        if config_frame is None:
            config_frame = sample_data_frame.cfg
        station_names = config_frame.get_station_name()
        phasor_channel_names = config_frame.get_channel_names()
        phasor_ph_units = config_frame.get_ph_units()

        n_stations = len(station_names)

        header_station_names = [st.strip() for st in station_names] * 2
        header_channel_names = ["Frequency"] * n_stations + ["Dfrequency"] * n_stations
        header_types = ["f"] * n_stations + ["Df"] * n_stations
        for st, ch, ph_type in zip(
            header_station_names, phasor_channel_names, phasor_ph_units
        ):
            for c, t in zip(ch, ph_type):
                [header_station_names.append(st.strip()) for _ in range(2)]
                header_channel_names.append(c.strip() + "_Magnitude")
                header_channel_names.append(c.strip() + "_Angle")
                header_types.append(f"{t[1]}_Magnitude")
                header_types.append(f"{t[1]}_Angle")

        if self.channel_selection is not None:
            channel_indexer = Indexer(
                header=dict(
                    station=header_station_names,
                    channel=header_channel_names,
                    measurement=header_types,
                )
            )
            self.channel_selection_idx = channel_indexer.get_col_idx(
                **self.channel_selection
            )

        if self.channel_selection_idx is None:
            self.channel_selection_idx = slice(None)

        return dict(
            station=np.array(header_station_names)[self.channel_selection_idx],
            channel=np.array(header_channel_names)[self.channel_selection_idx],
            measurement=np.array(header_types)[self.channel_selection_idx],
        )

    def data_frame_to_row(self, pmu_data_frame):
        t = pmu_data_frame.get_time_stamp()
        freq = np.array(pmu_data_frame.get_freq())
        dfreq = np.array(pmu_data_frame.get_dfreq())
        if self.substitute_zero_freq_with_nan:
            freq[freq == 0] = np.nan
            dfreq[dfreq == 0] = np.nan

        phasors = np.concatenate(
            pmu_data_frame.get_phasors(convert2polar=False)
        ).flatten()

        return t, np.concatenate([freq, dfreq, phasors])[self.channel_selection_idx]


class PMUFreqExtractor:
    def __init__(self, wanted_stations, stations=None, dataframe=None):
        if stations is None and dataframe is not None:
            stations = dataframe.cfg.get_station_name()
            
        self.idx, self.mask = lookup_strings(
            np.array([s.strip() for s in wanted_stations]),
            np.array([s.strip() for s in stations]),
            return_mask=True)
        self.ret_val = np.nan*np.zeros(len(self.mask))

    def get(self, freq):
        self.ret_val[:] = np.nan
        self.ret_val[self.mask] = np.array(freq)[self.idx]
        return self.ret_val


class PMUPhasorExtractor:
    def __init__(self,
            wanted=None,
            header=None,
            wanted_stations=None,
            wanted_channels=None,
            stations=None,
            channels=None,
            dataframe=None):
        
        if header is not None:
            stations = np.array([s for s, _ in header])
            channels = [np.array(c) for _, c in header]
        # elif stations is not None and channels is not None:
        #     stations = np.array([s.strip() for s in stations])
        #     channels = [np.array([c_.strip() for c_ in c]) for c in channels]
        elif dataframe is not None:
            stations = dataframe.cfg.get_station_name()
            channels = dataframe.cfg.get_channel_names()
        
        if isinstance(stations, str):
            stations = [stations]
            channels = [channels]


        stations = np.array([s.strip() for s in stations])
        channels = [np.array([c_.strip() for c_ in c]) for c in channels]

        
        if wanted is None:
            wanted = [*zip(wanted_stations, wanted_channels)]
        elif isinstance(wanted, tuple):
            wanted = [*zip(wanted[0], wanted[1])]
        
        self.idx = []
        for wanted_station, wanted_channels in wanted:
            station_search = stations == wanted_station.strip()
            if station_search.any():
                station_idx = np.argwhere(station_search)[0][0]
                channel_idx = []
                for wanted_channel in wanted_channels:
                    channel_search = channels[station_idx] == wanted_channel.strip()
                    if channel_search.any():
                        channel_idx.append(np.argwhere(channel_search)[0][0])
                    else:
                        print(f'Warning: Channel {wanted_channel} on station {wanted_station} not found.')    
                        channel_idx.append(None)
                self.idx.append((station_idx, channel_idx))
            else:
                print(f'Warning: Station name {wanted_station} not found.')
                self.idx.append((None, [None]*len(wanted_channels)))

    def get(self, phasors):
        if not isinstance(phasors[0], list):
            phasors = [phasors]
        phasors_out = []
        for idx in self.idx:
            station_idx, channel_idx = idx
            if station_idx is not None:
                phasors_out.append([phasors[station_idx][c]\
                    if c is not None else (np.nan,)*2 for c in channel_idx])
            else:
                phasors_out.append([(np.nan,)*2]*len(channel_idx))

        return phasors_out


if __name__ == '__main__':
    header = [
        ('PMU1', ['Phasor1.1', 'Phasor1.2']),
        ('PMU2', ['Phasor2.1', 'Phasor2.2', 'Phasor2.3']),
        ('PMU3', ['Phasor3.1']),
    ]
    wanted = [
        ('PMU2', ['Phasor2.3', 'Phasor2.1']),
        ('PMU4', ['Phasor1', 'Phasor2']),
        ('PMU3', ['Phasor3.1']),
        ('PMU123', ['Phasor12']),
        ('PMU23', ['Phasor1.1', 'Phasor1.5']),
    ]

    phasors = [[1.1, 1.2], [2.1, 2.2, 2.3], [3.1]]
    
    ph_ext = PMUPhasorExtractor(wanted, header)
    ph_ext.idx
    ph_ext.get(phasors)

    [station_idx for station_idx, channel_idx in ph_ext.idx]

    # Alternative specification:
    stations = ['PMU1', 'PMU2', 'PMU3']
    channels = [['Phasor1.1', 'Phasor1.2', 'Phasor1.3'], ['Phasor2.1', 'Phasor2.2'], ['Phasor3.1']]
    
    phasors = [[1.1, 1.2, 1.3], [2.1, 2.2], [3.1]]
    wanted_stations = ['PMU2', 'PMU3']
    wanted_channels = [['Phasor2.1'], ['Phasor3.1']]
    wanted = (wanted_stations, wanted_channels)

    ph_ext = PMUPhasorExtractor(wanted_stations=wanted_stations, wanted_channels=wanted_channels, stations=stations, channels=channels)
    print(ph_ext.get(phasors))


    # Note: DOes not work when same station given two times.
    wanted_stations = ["PMU2", "PMU3", "PMU2"]
    wanted_channels = [["Phasor2.1"], ["Phasor3.1"], ["Phasor2.1"]]
    wanted = (wanted_stations, wanted_channels)

    ph_ext = PMUPhasorExtractor(
        wanted_stations=wanted_stations,
        wanted_channels=wanted_channels,
        stations=stations,
        channels=channels,
    )
    print(ph_ext.get(phasors))