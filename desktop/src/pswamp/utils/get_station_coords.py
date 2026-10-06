# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from pswamp.streaming import get_last_message_from_topic
import numpy as np
import time
from pswamp.utils.misc import lookup_strings
from pswamp.database.base import get_from_database
from io import StringIO
import ezdxf
import pswamp.visualization.components.single_line_diagram as sld


# TODO: Calling these functions should be replaced with reading from database



def load_bus_coords_for_current_stations(config, return_3d=False, geo=True, sld_id=None):
    """Get coordinates for stations in PMU data frame"""
    while True:
        sample_pmu_data_frame = get_last_message_from_topic(
            topic=config["topics"]["pmudata"], **config["streaming"]
        )
        if sample_pmu_data_frame is not None:
            break
        else:
            time.sleep(1)
    
    stations = sample_pmu_data_frame.cfg.get_station_name()
    return stations, load_bus_coords_for_stations(config, stations, return_3d, geo, sld_id)

def load_bus_coords_for_stations(config, wanted_stations, return_3d=False, geo=True, sld_id=None):
    """Get coordinates for a subset of stations"""
    all_station_names, all_coords = load_bus_coords(config, return_3d, geo, sld_id)
    all_station_names = np.array([s.strip() for s in all_station_names])
    wanted_stations = np.array([s.strip() for s in wanted_stations])
    wanted_subset_idx, station_found_mask = lookup_strings(wanted_stations, all_station_names, return_mask=True)

    wanted_coords = np.nan*np.ones((len(wanted_stations), len(all_coords[0])))
    wanted_coords[station_found_mask, :] = np.array(all_coords)[wanted_subset_idx, :]
    
    return wanted_coords


def load_bus_coords(config, return_3d=False, geo=True, sld_id=None):
    """Get bus coordinates for all buses from pmu.coords topic"""
    # bus_names, bus_coords = get_last_message_from_topic(
        # topic=config["topics"]["pmu.coords"], **config["streaming"]
    # )
    sld_data = config["single_line_diagrams"][sld_id]
    k = sld_data.get("aspect_ratio", 1)
    k_dxf = sld_data.get("dxf_aspect_ratio", 1)

    db_kwargs = config["database"]
    # bus_coords = bus_coords[:, 0:2] if geo else bus_coords[:, 2:4]
    all_sld = get_from_database(db_kwargs, "single_line_diagrams")
    current_sld = all_sld[all_sld["name"] == sld_id]["data"].values
    if len(current_sld) == 0:
        raise Exception(f"Could not read SLD data for {sld_id}")
    
    dxf_data = current_sld[-1]
    dxf_file_stream = StringIO(dxf_data)
    doc = ezdxf.read(dxf_file_stream)
    bus_data = get_from_database(db_kwargs, "bus")

    bus_names, bus_coords = sld.get_buses(
        doc, bus_data["name"].to_numpy()
    )

    bus_coords[:, 1] *= k/k_dxf

    if return_3d:
        bus_coords_3d = np.hstack([bus_coords, np.ones((len(bus_coords), 1))])
        return bus_names, bus_coords_3d
    else:
        return bus_names, bus_coords

    

if __name__ == "__main__":
    from pswamp.test_utils.sample_datasets.minimal_case import create_minimal_test_case
    from nqkafka.utils import stop_server

    config, con, pmu = create_minimal_test_case()

    print(load_bus_coords(config, sld_id="sld1"))
    stop_server(config["streaming"]["bootstrap_servers"])

# if __name__ == '__main__':
#     config = {
#         'streaming': {
#             'bootstrap_servers': 'localhost:40000',
#             'type': "nqkafka"},
#         'topics': {
#             'pmudata': 'pmudata',
#             'pmu.coords': 'pmu.coords'
#         }
#     }

#     stations, coords = load_bus_coords_for_current_stations(config)
#     print(coords)

#     all_coords = load_bus_coords(config)
#     print(all_coords)
