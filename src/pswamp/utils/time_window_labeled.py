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

from pswamp.utils.time_window import TimeWindow, GrowingTimeWindow
import numpy as np
from collections import OrderedDict


def table_to_strarray(cols, data):
    entries = [tuple(row) for row in zip(*data)]
    max_item_len = np.max([[len(item) for item in row] for row in entries])
    dtypes = [(dtype, f'<U{max_item_len}') for dtype in cols]
    return np.array(entries, dtype=dtypes)


class Indexer:
    def __init__(self, n_cols=None, header=None):
        if isinstance(header, dict):
            header_row_names = header.keys()
            header_values = header.values()
        elif isinstance(header, list):
            if isinstance(header[0], str):
                n_cols = len(header)
                header_values = [header]
                n_header_rows = 1
                header_row_names = ['0']
            elif isinstance(header[0], list):
                n_cols = len(header[0])
                n_header_rows = len(header)
                header_values = header
                header_row_names = [f"{i}" for i in range(n_header_rows)]

        elif header is None and n_cols is not None:
            header_values = [[f"{i}" for i in range(n_cols)]]
            header_row_names = ['0']
        else:
            print('Either number of columns (n_cols) or header must be specified in Indexer')
        
        self.header = table_to_strarray(header_row_names, header_values)
        self.n_cols = len(self.header)

    def get_col_idx(self, *args, **kwargs):

        if len(args) > 0 and isinstance(args[0], tuple):
            collected_indices = []
            for query in args:
                #  print(query)
                 collected_indices.append(self.get_col_idx_single_query(*query))

            return np.concatenate(collected_indices)
            # self.get_col_idx_single_query(*args, **kwargs)
            # for item in args:
            #     keep_idx_tmp = np.ones_like(keep_idx, dtype=bool)
            #     # np.equal(self.header, item)
            #     for key, item_ in zip(self.header.dtype.names, item):
            #         keep_idx_tmp *= self.header[key] == item_ 
                
            #     for h in self.header:
            #         if h == item:
            #     for key, item_ in zip(self.header.dtype.names, item):

                    
            #         pass
        else:
            return self.get_col_idx_single_query(*args, **kwargs)
    
    def get_col_idx_single_query(self, *args, **kwargs):
        keep_idx = np.ones(self.n_cols, dtype=bool)
        
        if isinstance(args, str):
            args = (args,)
        for key, item in zip(self.header.dtype.names, args):
            if item is not None:
                if isinstance(item, (list, np.ndarray)):
                    keep_idx *= self.header[key] in [item_.strip() for item_ in item]
                    # for item_ in item:
                        # keep_idx *= self.header[key] == item_.strip()
                else:
                    keep_idx *= self.header[key] == item.strip()

        for key, item in kwargs.items():
            if isinstance(item, (list, np.ndarray)):
                keep_idx_tmp = np.zeros_like(keep_idx, dtype=bool)
                for item_ in item:
                    keep_idx_tmp += self.header[key] == item_.strip()
                keep_idx *= keep_idx_tmp
            else:
                keep_idx *= self.header[key] == item.strip()

        return np.where(keep_idx)[0]


class TimeWindowLabeled(TimeWindow):
    """Stores the most recent n_samples of multichannel data, and corresponding time stamps. Updating with a new
    set of measurements is efficient, since only one row in the data array (self._data) is overwritten."""

    def __init__(
        self, n_samples=10, n_cols=None, header=None, dtype=float,
    ):
        """

        Args:
            n_samples: Number of samples in the time window.
            n_cols: Must be specified if header is not specified.
            header: dict or list or, specifying data header. The header is used to lookup columns.
            dtype: Data type (float, complex, etc.).
        """

        self.indexer = Indexer(n_cols=n_cols, header=header)
        self.header = self.indexer.header

        super().__init__(n_samples=n_samples, n_cols=self.indexer.n_cols, dtype=dtype)

    def get_col_idx(self, *args, **kwargs):

        return self.indexer.get_col_idx(*args, **kwargs)

    def get_col_str(self, *args, **kwargs):
        """
        Get data columns based on lookup of strings in self.header.
        Args:
            *args: Strings to look for. Look for first arg in first header row, second in second row, and so on.
            **kwargs: Dictionary with header rows to lookup as keys and entries as values

        Returns:
            Data array.

        """
        col_idx = self.get_col_idx(*args, **kwargs)
        return super().get_col(col_idx)
    

class GrowingTimeWindowLabeled(GrowingTimeWindow, TimeWindowLabeled):
    def __init__(
        self, n_samples=None, n_cols=None, header=None, dtype=float,
    ):

        self.indexer = Indexer(n_cols=n_cols, header=header)
        self.header = self.indexer.header

        super().__init__(n_samples=n_samples, n_cols=self.indexer.n_cols, dtype=dtype)

    def get_col_str(self, *args, **kwargs):
        """
        Get data columns based on lookup of strings in self.header.
        TODO: This function is defined twice, also in TimeWindowLabeled.
        If not redefined here, it will use TimeWindow's get_col, not
        GrowingTimeWindow's variant. Could probably be done in a nicer way.

        Args:
            *args: Strings to look for. Look for first arg in first header row, second in second row, and so on.
            **kwargs: Dictionary with header rows to lookup as keys and entries as values

        Returns:
            Data array.

        """
        col_idx = self.get_col_idx(*args, **kwargs)
        return super().get_col(col_idx)


if __name__ == "__main__":

    gtw = GrowingTimeWindowLabeled(n_cols=5)
    # print(gtw.header)
    # gtw.get_col_str()



    header=dict(
        station=   ['SW1',	    'SW1',      'N1',	'N2'],
        channel=   ['V',	    'I:L1-2',   'I',	'V'],
        type=      ['v',	    'i',	    'i',    'v'],
    )
    
    tw = TimeWindowLabeled(header=header)
    
    assert((tw.get_col_idx(channel='V') == [0, 3]).all())

    # No column headers (as with TimeWindow)
    tw = TimeWindowLabeled(n_cols=3)
    assert tw.n_cols == 3
    tw.header
    assert (tw.get_col_idx() == [0, 1, 2]).all()
    assert (tw.get_col_idx('1') == [1]).all()

    # Specify column headers, but not header row names:
    header = [
        ['Col1', 'Col2', 'Col3', 'Col4'],
        ['Col1', 'Col2', 'Col2', 'Col4']
    ]
    tw = TimeWindowLabeled(header=header)
    tw.header['1']
    tw.get_col_idx('Col3', 'Col2')
    # tw.get_col_idx(['Col3', 'Col4'], 'Col2')

    # tw.get_col_idx(('Col1', 'Col2'))

    header = dict(
        station=    ['N',    'N',     'S',    'S',     'E',     'W'],
        channel=    ['freq', 'V',     'freq', 'V',     'V',     'V'],
        type=       ['f',    'v_ang', 'f',    'v_ang', 'v_mag', 'v_ang']
    )
    tw = TimeWindowLabeled(header=header)
    
    assert np.array_equal(tw.get_col_idx('N'), np.array([0, 1]))
    assert np.array_equal(tw.get_col_idx('S'), np.array([2, 3]))
    assert np.array_equal(tw.get_col_idx(channel='freq'), np.array([0, 2]))
    assert np.array_equal(tw.get_col_idx(station='N', channel='freq'), np.array([0]))
    assert np.array_equal(tw.get_col_idx(station=['N', 'W'], channel='V'), np.array([1, 5]))
    tw.get_col_idx(station=['N', 'W'], channel='V')

    assert np.array_equal(tw.get_col_idx(('N', 'V', 'v_ang'), ('N', 'freq'), ('W')), np.array([1, 0, 5]))
    # tw.get_col_idx(('N', 'V', 'v_ang'), ('N'), ('W'))
    # tw.header[tw.get_col_idx(('N', 'V', 'v_ang'), ('N'), ('W'))]

    # def fun(*args, **kwargs):
    #     print(args)
    #     print(kwargs)

    # args_and_kwargs = ...
    # fun()
