from pswamp import load_config
from pswamp.database import get_from_database
from pswamp.utils import get_station_coords
from pswamp.streaming import get_last_message_from_topic


if __name__ == "__main__":
    config = load_config("examples/nordic44_rtsim/")
    config["database"]
    pmu_df = get_from_database(config, "pmu")
    pmu_df

    wanted_stations = [
        "3244",
        "3245",
        "3249",
        "3300",
        "3359",
        "3360",
    ]
    name, coord = get_station_coords.load_bus_coords(config, geo=True)
    coord_subset = get_station_coords.load_bus_coords_for_stations(config, wanted_stations, geo=True)
    coord = get_station_coords.load_bus_coords_for_current_stations(config)

    # sample_pmu_data_frame = get_last_message_from_topic(
    #     config["topics"]["pmudata"], **config["streaming"]
    # )

    pmu_df.set_index("name").loc[wanted_stations]

    coord_subset