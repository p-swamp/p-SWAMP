"""The islanding analysis: which stations' frequencies move together.

The desktop package's ``detect_islands`` (``pswamp.monitoring.islanding``),
with two fixes: its groups could overlap (a station close to two references
joined both), and it stopped after ten groups, leaving any further stations in
none. Here every station with data is in exactly one group, and the largest
group (the main system) is returned too, with every group's mean frequency.
"""

import numpy as np

SMOOTHING = 10  # samples in the moving average


def moving_average(x, w):
    return np.convolve(x, np.ones(w), "valid") / w


def detect_islands(t, data, threshold=0.05):
    """Group the stations whose smoothed frequencies stay within ``threshold`` (RMS) of each other.

    A group is the stations close to its reference, the first station not yet
    in a group. Returns ``(t[-1], groups, means)``: every group, largest first
    (so the first is the main system and the rest are islands), each an array of
    column indexes, and each group's mean smoothed frequency over the window. A
    column with NaN anywhere in the window is in no group. ``None`` until the
    window has filled (NaN in ``t``).
    """
    if np.any(np.isnan(t)):
        return None

    freq = np.array([moving_average(f, SMOOTHING) for f in data.T]).T
    assigned = np.isnan(np.mean(freq, axis=0))

    groups = []
    while not np.all(assigned):
        ref = np.argmax(~assigned)
        rms = np.linalg.norm(freq[:, [ref]] - freq, axis=0) / np.sqrt(len(t))
        members = (rms < threshold) & ~assigned
        members[ref] = True  # so each pass assigns at least one station
        assigned |= members
        groups.append(np.where(members)[0])

    groups.sort(key=len, reverse=True)
    means = [float(np.mean(freq[:, group])) for group in groups]
    return t[-1], groups, means
