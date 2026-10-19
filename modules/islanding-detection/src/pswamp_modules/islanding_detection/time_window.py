# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""``TimeWindow``: the desktop package's ring buffer (``pswamp.utils.time_window``),
cut to what the module uses. No lock: a module's ``process`` is never called
concurrently."""

import numpy as np


class TimeWindow:
    """Stores the most recent n_samples of multichannel data, and corresponding time stamps. Updating with a new
    set of measurements is efficient, since only one row in the data array (self._data) is overwritten."""

    def __init__(self, n_samples=100, n_cols=0, dtype=float):
        """
        Args:
            n_samples: Number of samples in the time window.
            n_cols: Number of channels.
            dtype: Data type (float, complex, etc.).
        """
        self.n_samples = n_samples
        self.n_cols = n_cols

        self._data = np.full((n_samples, n_cols), np.nan, dtype=dtype)
        self._time = np.full(n_samples, np.nan)

        self._k = 0  # This is the index of the row to be overwritten on next update.

    def get(self):
        """Time vector and data array, oldest sample first. NaN where nothing has been appended yet."""
        return np.roll(self._time, -self._k), np.roll(self._data, -self._k, axis=0)

    def append(self, new_time, new_data):
        """
        Append a new set of measurement data, and corresponding time stamp.
        Args:
            new_time: Time stamp. Single number.
            new_data: Row of measurement data.
        """
        self._time[self._k] = new_time
        self._data[self._k] = new_data
        self._k = (self._k + 1) % self.n_samples
