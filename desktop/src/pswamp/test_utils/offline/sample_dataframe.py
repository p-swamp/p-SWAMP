# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from synchrophasor.simplePMU import SimplePMU
from pprint import pprint
from queue import Queue

"""
The purpose of this script is to quickly establish config- and data frames for a given PMU/PDC data stream,
allowing code to be developed for handling the frames without any actual streaming happening.
"""


def create_sample_data_frame():
    station_names = ['PMU1', 'PMU2', 'PMU3']
    channel_names = [
        ['Phasor1.1', 'Phasor1.2'],
        ['Phasor2.1', 'Phasor2.2', 'Phasor2.3'],
        ['Phasor3.1'],
    ]
    channel_types = [
        ['v', 'i'],
        ['v', 'i', 'v'],
        ['i'],
    ]
    id_codes = [1410, 1411, 1412]
    pdc_id = 1

    pmu = SimplePMU(
        '', '',
        publish_frequency=50,
        station_names=station_names,
        channel_names=channel_names,
        pdc_id=pdc_id,
        channel_types=channel_types,
        id_codes=id_codes
    )

    #
    config_frame = pmu.pmu.cfg2
    config_frame.get_station_name()
    config_frame.get_channel_names()
    config_frame.get_ph_units()

    # Workaround to get the PMU dataframe
    my_queue = Queue()
    pmu.pmu.client_buffers.append(my_queue)
    pmu.publish()
    data_frame = my_queue.get()

    return data_frame


if __name__ == "__main__":

    data_frame = create_sample_data_frame()
    data_frame.get_phasors()
    data_frame.cfg.get_station_name()
    data_frame.cfg.get_channel_names()
    data_frame.cfg.get_ph_units()
    data_frame.cfg.get_data_rate()
