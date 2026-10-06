import numpy as np
import geojson
from pathlib import Path


def flatten_list_insert_nan(listlist):
    dim = listlist[0].shape[1]
    z = [*zip(listlist, [np.ones((1, dim)) * np.nan] * len(listlist))]
    flattened_list = [y for x in z for y in x]
    return np.vstack(flattened_list) if len(flattened_list) > 0 else np.empty((0, dim))


if __name__ == "__main__":

    # Load grid data
    path_0 = Path(__file__).parent
    folder = "scandinavia"
    path = path_0 / folder
    lines_xy = []
    # years = []
    # line_lengths = []
    voltages = []
    names = []
    # grid_levels = []
    print('Loading data from folder "{}"...'.format(folder))
    with open(path / "export.geojson", encoding="utf-8") as f:
        gj = geojson.load(f)
        # features = gj['features'][0]
        # k = 0
        for feature in gj["features"]:
            # print(feature['properties']['navn'])
            # if feature['properties']['navn'] is not None and "L0752 USTA-" in feature['properties']['navn']:
            # print(feature['properties']['navn'])
            # break
            # year = feature['properties']['driftsattaar']
            # grid_level = feature['properties']['nettnivaa']
            # if year is not None and voltage is not None:

            if feature["geometry"]["type"] == "LineString":
                voltage = (
                    feature["properties"]["voltage"]
                    if "voltage" in feature["properties"]
                    else 0
                )
                if isinstance(voltage, int):
                    voltage = voltage
                elif isinstance(voltage, str):
                    voltage = voltage.split(";")[0]
                    if voltage.isnumeric():
                        voltage = int(voltage)
                    else:
                        voltage = 0
                name = (
                    feature["properties"]["id"]
                    if "id" in feature["properties"]
                    else "?"
                )

                lines_xy.append(np.array(feature["geometry"]["coordinates"]))
                voltages.append(voltage)
                names.append(name)
            # elif feature['geometry']['type'] == 'MultiLineString':
            #     print(feature['geometry']['type'])
            #     # break
            #     # lines_xy.append(np.vstack([coords for coords in feature['geometry']['coordinates']]))
            #     lines_xy.append(flatten_list_insert_nan(feature['geometry']['coordinates']))
            # elif feature['geometry']['type'] == 'Polygon':
            #     print(feature['geometry']['type'])
            # else:
            #     print('Warning: Undefined geometry type "{}" found.'.format(feature['geometry']['type']))

            # years.append(year)

            # line_lengths.append(len(lines_xy[-1]))
            # grid_levels.append(grid_level)

    lines_xy = np.array(lines_xy, dtype=object)

    voltages = np.array(voltages, dtype=int)
    # plt.hist(voltages, bins=100)
    # plt.show(block=True)
    hv = 200000
    mv = 40000

    hv_idx = voltages >= hv
    mv_idx = (~hv_idx) & (voltages > mv)
    lv_idx = ~(hv_idx | mv_idx)

    lines_hv = lines_xy[hv_idx]
    lines_mv = lines_xy[mv_idx]
    lines_lv = lines_xy[lv_idx]

    # lines_xy_flat = flatten_list_insert_nan(lines_xy)
    lines_hv = flatten_list_insert_nan(lines_hv)
    lines_mv = flatten_list_insert_nan(lines_mv)
    lines_lv = flatten_list_insert_nan(lines_lv)
    # for line_xy in lines_xy:
    #     if not line_xy.shape[1] == 2:
    #         print(line_xy.shape[1])
    lines_hv = np.hstack([lines_hv, np.zeros((len(lines_hv), 1))])
    lines_mv = np.hstack([lines_mv, np.zeros((len(lines_mv), 1))])
    lines_lv = np.hstack([lines_lv, np.zeros((len(lines_lv), 1))])
    k = 1 / np.cos(60 / 180 * np.pi)

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 3, subplot_kw={"aspect": "equal"})
    for ax_, lines in zip(ax, [lines_hv, lines_mv, lines_lv]):
        ax_.plot(lines[:, 0], k * lines[:, 1])
    plt.show(block=True)

    out_file_path = path_0 + folder / "numpy_data.npz"
    np.savez(out_file_path, lines_hv=lines_hv, lines_mv=lines_mv, lines_lv=lines_lv)

    data = np.load(out_file_path)
    for key in ["lines_lv", "lines_mv", "lines_hv"]:
        plt.plot(data[key][:, 0], data[key][:, 1])

    plt.show(block=True)
