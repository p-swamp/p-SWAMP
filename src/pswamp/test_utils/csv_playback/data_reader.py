import sys, os
# sys.path.append(os.getcwd() + '\src')
import numpy as np
from pathlib import Path
from datetime import datetime


def float_nan(x, replace_empty_string_with=np.nan):
    # if isinstance(x, np.array):
    #     x.astype(float)
    # else:
    return float(x) if x != '' else replace_empty_string_with


class DataReader:
    def __init__(self, pmu_data_folder, case_name_hint='', input_given_in_rad=False, skip_rows=0, skip_until_time=None) -> None:

        self.pmu_data_folder = pmu_data_folder
        self.case_name_hint = case_name_hint
        self.original_case_name_hint = case_name_hint
        self.input_given_in_rad = input_given_in_rad
        self.current_case_name_hint = self.case_name_hint

        # Initialize file readers
        self.file_paths, self.file_readers = self.create_file_readers(self.pmu_data_folder, self.case_name_hint)
        self.file_readers_next = {}
        self.file_readers_paused = np.zeros(len(self.file_readers), dtype=bool)

        column_names_per_file = [[item.strip().replace('"', '') for item in self.read_row_from_file(file_reader).split(',')] for file_reader in self.file_readers.values() ]
        
        self.column_names = column_names = np.concatenate(column_names_per_file, dtype=str)
        # column_names = np.array([item.strip() for file_reader in self.file_readers.values() for item in next(file_reader).split(',')], dtype=str)

        self.idx_time = np.flatnonzero(np.core.defchararray.find(column_names,'Timestamp')!=-1)
        self.idx_freq = np.flatnonzero(np.core.defchararray.find(column_names,'Frequency')!=-1)
        self.idx_dfreq = np.flatnonzero(np.core.defchararray.find(column_names,'Dfrequency')!=-1)

        self.stations = stations = []
        self.pmu_ids = pmu_ids = []
        # countries = []

        self.idx_phasors = dict()  # .fromkeys((pmu_ids, stations))  # zip(pmu_ids, stations))
        
        self.channels = channels = []
        self.channel_types = channel_types = []

        # These are used to determine wheter phasors are currents or voltages

        for file_path, column_names_in_file in zip(self.file_paths, column_names_per_file):
            pmu_id = self.get_pmu_id(file_path)
            # country, pmu_id, station_from_folder = str(file_path.name).split(' ', 2)
            station = column_names_in_file[1].split(':')[0]
            assert np.all([c.split(':')[0] == station for c in column_names_in_file if 'Timestamp' not in c])
            stations.append(station)
            pmu_ids.append(pmu_id)
        
        # for pmu_id, station in pmu_ids, stations:
            mag_idx = self.search_for_idx(column_names, [station, '_Magnitude'])
            ang_idx = self.search_for_idx(column_names, [station, '_Angle'])
            mag_columns = [c[:-10] for c in column_names[mag_idx]]
            ang_columns = [c[:-6] for c in column_names[ang_idx]]
            assert np.array_equal(mag_columns, ang_columns)
            
            voltage_type = self.search_for_idx(mag_columns, self.voltage_search_terms().split(', '), mode='any', return_mask=True)
            current_type = self.search_for_idx(mag_columns, self.current_search_terms().split(', '), mode='any', return_mask=True)
            if not np.all(voltage_type + current_type):
                # print(mag_columns)
                pass
            voltage_type += ~(voltage_type + current_type)
            assert np.all(voltage_type + current_type)

            channel_types.append(['v' if v_or_i else 'i' for v_or_i in voltage_type])

            channels.append([c.split(':')[1] for c in mag_columns])

            self.idx_phasors[(pmu_id, station)] = [mag_idx, ang_idx]
            
        self.skip_rows = skip_rows
        self.skip_seconds_until_time = skip_until_time
        # if self.skip_n_rows > 0:
            # self.skip_rows(self.skip_n_rows)
        if self.skip_seconds_until_time is not None:
            self.skip_until_time(self.skip_seconds_until_time)
            
        # if self.skip_rows > 0:
        #     while True:
        #         rows = self.read_next_rows()
        #         time_stamp = self.get_time_stamp(rows)
        #         if round(time_stamp) == round(time_stamp, 2):
        #             break
            

    
    def reset(self):
        self.case_name_hint = self.original_case_name_hint
        self.file_paths, self.file_readers = self.create_file_readers(self.pmu_data_folder, self.case_name_hint)
        self.file_readers_paused = np.zeros(len(self.file_readers), dtype=bool)
        _ = self.read_next_rows()
        if self.skip_seconds_until_time is not None:
            self.skip_until_time(self.skip_seconds_until_time)

    
    def skip_until_time(self, target_time_stamp):
        while True:
            # rows = np.array([item.strip() for file_reader in self.file_readers.values() for item in self.read_row_from_file(file_reader).split(',')], dtype=object)
            # current_time_stamp = self.get_time_stamp(rows)
            rows = self.read_next_rows()
            time_stamp = self.get_time_stamp(rows)
            if time_stamp >= target_time_stamp:
                break

    def create_file_readers(self, pmu_data_folder, case_name_hint):
        file_paths = self.get_file_path_list(
            pmu_data_folder, case_name_hint)
        # print(len(file_paths))

        file_readers = {}
        for file_path in file_paths:
            pmu_id = self.get_pmu_id(file_path)
            file_readers[pmu_id] = self.new_file_reader(file_path)

        return file_paths, file_readers

    def voltage_search_terms(self):
        return 'U_3ph'
    
    def current_search_terms(self):
        return 'I_3ph'

    @staticmethod
    def search_for_idx(list_of_strings, search_terms, mode='all', return_mask=False):
        if mode == 'all':
            mask = np.ones(len(list_of_strings), dtype=bool)
            for search_term in search_terms:
                mask *= (np.core.defchararray.find(list_of_strings, search_term) != -1)
        else:  # elif mode == 'any':
            mask = np.zeros(len(list_of_strings), dtype=bool)
            for search_term in search_terms:
                mask += (np.core.defchararray.find(list_of_strings, search_term) != -1)
        if return_mask:
            return mask
        else:
            return np.flatnonzero(mask)
        
    def get_time_stamp(self, rows):
        time_stamp, counts = np.unique(rows[self.idx_time][~self.file_readers_paused], return_counts=True)
        if len(time_stamp) > 1:
            print(f'Warning: Time stamps are not correct at time {time_stamp[0]}')
        return round(float(time_stamp[0])/2, 2)*2

        # return ...[self.idx_time]...
        
    @staticmethod
    def str2date(date_string):
        return datetime.strptime(date_string, '"%Y/%m/%d %H:%M:%S.%f"')
    
    def ensure_radians(self, angle, substitute_nan_with=0):
        if np.isnan(angle):
            angle = substitute_nan_with
        return angle if self.input_given_in_rad else angle*np.pi/180

    def handle_end_of_file(self):
        print('Reached end of file!')
        
    def get_next_case_name_hint(self, case_name_hint):
        return None  # f'{self.case_name_hint[:-1]}{int(self.case_name_hint[-1])+1}'
    

    def read_next_rows(self):
        rows = []
        for i, (pmu_id, file_reader) in enumerate(self.file_readers.items()):
            if self.file_readers_paused[i]:
                rows.append(self.previous_rows[i])
                continue

            try:
                row = self.read_row_from_file(file_reader)
            except StopIteration:
                if pmu_id not in self.file_readers_next:
                    self.current_case_name_hint = self.get_next_case_name_hint(
                        self.current_case_name_hint)
                    if self.current_case_name_hint is None:
                        raise StopIteration
                    _, self.file_readers_next = self.create_file_readers(
                        self.pmu_data_folder, self.current_case_name_hint)
                    if pmu_id not in self.file_readers_next:
                        # No next file found for current PMU
                        print(f'No next file found for file reader {file_reader}')
                        rows.append(self.previous_rows[i])
                        continue
                        # raise StopIteration
                file_reader = self.file_readers_next.pop(pmu_id)
                next(file_reader)
                print(f'Jumped to next file reader {file_reader}')
                row = self.read_row_from_file(file_reader)
                self.file_readers[pmu_id] = file_reader

            rows.append(np.array([item.strip()
                        for item in row.split(',')], dtype=object))

        self.previous_rows = [row.copy() for row in rows]

        time_stamps = np.array([row[0] for row in rows])
        time_stamp, counts = np.unique(time_stamps, return_counts=True)
        actual_time_stamp = time_stamp[np.argmax(counts)]
        self.file_readers_paused[:] = False
        self.file_readers_paused[time_stamps != actual_time_stamp] = True

        paused_idx = np.where(self.file_readers_paused)[0]
        for idx in paused_idx:
            rows[idx][:] = ''

        rows = np.concatenate(rows, dtype=object)
        return rows
    
    def get_next_row(self):
        rows = self.read_next_rows()
        [self.read_next_rows() for _ in range(self.skip_rows)]

        data_kwargs = {}

        data_kwargs['time_stamp'] = self.get_time_stamp(rows)

        freq_str = np.array(rows[self.idx_freq], dtype=str)
        freq_str[freq_str == ''] = '0'
        freq_str[freq_str == 'nan'] = '0'

        dfreq_str = np.array(rows[self.idx_dfreq], dtype=str)
        dfreq_str[dfreq_str == ''] = '0'
        dfreq_str[dfreq_str == 'nan'] = '0'

        data_kwargs['freq'] = freq_str.astype(float) if len(
            freq_str) > 0 else None  # np.array(rows[self.idx_freq], dtype=float)
        data_kwargs['dfreq'] = dfreq_str.astype(float) if len(
            dfreq_str) > 0 else None  # np.array(rows[self.idx_dfreq], dtype=float)

        data_kwargs['phasors'] = [[(float_nan(rows[i_m]), self.ensure_radians(float_nan(
            rows[i_a], replace_empty_string_with=0))) for i_m, i_a in zip(idx[0], idx[1])] for idx in self.idx_phasors.values()]
        # for idx in self.idx_phasors.values():
        #     for i_m, i_a in zip(idx[0], idx[1]):
        #         i_m
        # self.time_stamp_prev = time_stamp

        return data_kwargs

    def get_next_case_name_hint(self, case_name_hint):
        return None
    
    def get_file_path_list(self, pmu_data_folder, case_name_hint):
        pmu_data_folder = Path(pmu_data_folder)
        file_paths = []
        for file_name in os.listdir(pmu_data_folder):
            if case_name_hint is None or case_name_hint in file_name:
                file_paths.append(pmu_data_folder/file_name)

        return file_paths

    def get_pmu_id(self, file_path):
        pmu_id = str(
            file_path.name).split('_')[-1][:-4]
        return int(pmu_id)
    
    def read_row_from_file(self, file_reader):
        return next(file_reader)
    
    def new_file_reader(self, file_path):
        return open(file_path)
