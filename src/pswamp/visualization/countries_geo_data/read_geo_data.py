# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

import shapefile
import numpy as np
import pathlib


def read_geo_data(countries="All"):

    path = (
        pathlib.Path(__file__).parent.parent
        / "countries_geo_data"
        / "99bfd9e7-bb42-4728-87b5-07f8c8ac631c2020328-1-1vef4ev.lu5nk.shp"
    )
    # print(current_path)
    # print(path.parent.parent)
    # path = current_path.joinpath('\data\geo_data\countries_shapefile\99bfd9e7-bb42-4728-87b5-07f8c8ac631c2020328-1-1vef4ev.lu5nk')
    # print(path)

    # path = pswamp_PATH + r'\data\geo_data\countries_shapefile\99bfd9e7-bb42-4728-87b5-07f8c8ac631c2020328-1-1vef4ev.lu5nk'
    shp = open(path.with_suffix(".shp"), "rb")
    dbf = open(path.with_suffix(".dbf"), "rb")
    sf = shapefile.Reader(shp=shp, dbf=dbf)
    # sf = shapefile.Reader(file_path)

    n = len(sf.shapes())

    points_all = []
    for i in range(n):
        if countries == "All" or sf.record(i)[1] in countries:
            shape = sf.shape(i)
            points = np.array(shape.points)
            parts = shape.parts
            n_parts = len(parts)
            for j in range(n_parts):
                start_idx = parts[j]
                if j == (n_parts - 1):
                    end_idx = -1
                else:
                    end_idx = parts[j + 1]

                points_closed = np.vstack(
                    [
                        points[start_idx:end_idx, :],
                        points[start_idx, :],
                        np.nan * np.ones((1, 2)),
                    ]
                )
                points_all.append(points_closed)
                # plt.plot(points_closed[:, 0], points_closed[:, 1])

    return np.vstack(points_all)


if __name__ == '__main__':
    data = read_geo_data()
    data = read_geo_data('All')
    data = read_geo_data(['Norway', 'Sweden'])

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1)
    ax.plot(data[:, 0], data[:, 1]*2)
    ax.set_aspect(1)
    plt.show()
