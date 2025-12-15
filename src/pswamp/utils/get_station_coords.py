from pswamp.streaming.kafka_extras import get_last_message_from_topic
import numpy as np
import time
from pswamp.utils.misc import lookup_strings


def load_bus_coords_for_current_stations(config, return_3d=False, geo=True):
    """Get coordinates for stations in PMU data frame"""
    while True:
        sample_pmu_data_frame = get_last_message_from_topic(
            config['kafka'], config['topics']['pmudata']
        )
        if not sample_pmu_data_frame is None:
            break
        else:
            time.sleep(1)
    
    stations = sample_pmu_data_frame.cfg.get_station_name()
    return stations, load_bus_coords_for_stations(config, stations, return_3d, geo)

def load_bus_coords_for_stations(config, wanted_stations, return_3d=False, geo=True):
    """Get coordinates for a subset of stations"""
    all_station_names, all_coords = load_bus_coords(config, return_3d, geo=geo)
    all_station_names = np.array([s.strip() for s in all_station_names])
    wanted_stations = np.array([s.strip() for s in wanted_stations])
    wanted_subset_idx, station_found_mask = lookup_strings(wanted_stations, all_station_names, return_mask=True)

    wanted_coords = np.nan*np.ones((len(wanted_stations), len(all_coords[0])))
    wanted_coords[station_found_mask, :] = np.array(all_coords)[wanted_subset_idx, :]
    
    return wanted_coords


def load_bus_coords(config, return_3d=False, geo=True):
    """Get bus coordinates for all buses from pmu.coords topic"""
    bus_names, bus_coords = get_last_message_from_topic(
        config['kafka'], config['topics']['pmu.coords']
    )

    bus_coords = bus_coords[:, 0:2] if geo else bus_coords[:, 2:4]

    if return_3d:
        bus_coords_3d = np.hstack([bus_coords, np.ones((len(bus_coords), 1))])
        return bus_names, bus_coords_3d
    else:
        return bus_names, bus_coords

    


if __name__ == '__main__':
    config = {
        'kafka': {
            'bootstrap_servers': 'localhost:40000',
            'use_nqkafka': True},
        'topics': {
            'pmudata': 'pmudata',
            'pmu.coords': 'pmu.coords'
        }
    }

    stations, coords = load_bus_coords_for_current_stations(config)
    print(coords)

    all_coords = load_bus_coords(config)
    print(all_coords)