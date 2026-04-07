# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

import numpy as np

def generate_pmu_data(n_stations=40, n_channels=1, t_end=10, dt=0.02):
    
    station_names = ['PMU{}'.format(i) for i in range(n_stations)]
    channel_names = [['Ph{}'.format(j) for j in range(n_channels)] for _ in range(n_stations)]

    # Generate some random time series
    t = np.arange(0, t_end, dt)
    phasor_data = []
    for channel_names_ in channel_names:
        angles = 1e-2*np.cumsum(np.random.randn(len(t), len(channel_names_)), axis=0)
        magnitudes = 1 + 1e-3*np.cumsum(np.random.randn(len(t), len(channel_names_)), axis=0)
        phasors_pmu = magnitudes*np.exp(1j*angles)
        phasors_pmu -= (phasors_pmu[-1, :] - phasors_pmu[0, :])[None, :] * t[:, None] / (t[-1] - t[0])

        phasor_data.append(phasors_pmu)

    return dict(
        stations=station_names,
        channels=channel_names,
        time=t,
        phasors=phasor_data,
    )
