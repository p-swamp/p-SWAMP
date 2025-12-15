import numpy as np

try:
    from sld_coords import load as n44_coordinates_sld
# import sld_coords
except ImportError:
    try:
        from data.sld_coords import load as n44_coordinates_sld
    except ImportError:
        from examples.nordic44_rtsim.data.sld_coords import load as n44_coordinates_sld



def convert_to_right_format(data):
    data = np.array(data)
    bus_names = data[:, 0]
    x = data[:, 1].astype(float)
    y = data[:, 2].astype(float)
    return bus_names, np.vstack([x, y]).T


def n44_coordinates():
    return convert_to_right_format([
        ['3000',    18.151138,     60.387936],
        ['3020',    17.998299,     60.440261],
        ['3100',    17.154818,     63.194228],
        ['3115',    19.821558,     66.959663],
        ['3200',    14.321606,     57.709782],
        ['3244',    14.439895,     59.316428],
        ['3245',    13.431513,     63.360424],
        ['3249',    15.058749,     65.153912],
        ['3300',    16.447415,     57.268563],
        ['3359',    12.112963,     57.260886],
        ['3360',    12.313982,     57.79208],
        ['3701',    15.54665,      65.549947],
        ['5100',    10.300185,     61.314765],
        ['5101',    10.784356,     59.925609],
        ['5102',    8.446858,      60.413234],
        ['5103',    9.650243,      59.671627],
        ['5300',    6.779807,      60.446208],
        ['5301',    7.114618,      60.862271],
        ['5304',    8.208738,      60.534367],
        ['5305',    7.502838,      60.36823],
        ['5400',    10.7811,       59.947746],
        ['5401',    10.28433,      59.912951],
        ['5402',    9.931822,      59.97139],
        ['5500',    10.751985,     59.916819],
        ['5501',    9.6057,        59.213829],
        ['5600',    8.01848,       58.165456],
        ['5601',    5.706114,      59.059368],
        ['5602',    10.215966,     59.132521],
        ['5603',    8.771641,      58.464498],
        ['5610',    8.017794,      58.165999],
        ['5620',    6.817281,      58.277387],
        ['6000',    6.637356,      59.515704],
        ['6001',    8.34529,       60.597591],
        ['6100',    6.017187,      59.858172],
        ['6500',    10.396532,     63.435459],
        ['6700',    13.796335,     66.149594],
        # ['6700-mod',    66.149594+0.5, 13.796335+0.5],
        ['6701',    17.463908,     68.672243],
        ['7000',    24.942307,     60.174729],
        ['7010',    28.617038,     61.040483],
        ['7020',    24.942518,     60.155244],
        ['7100',    25.407037,     65.143089],
        ['8500',    13.005346,     55.610594],
        ['8600',    13.030715,     55.546178],
        ['8700',    14.691093,     56.896229],
    ])


# def n44_coordinates_sld():
#     names, coords = convert_to_right_format([
#         ['5305', 320.0, 81.0],
#         ['5301', 347.0, 109.0],
#         ['5300', 375.0, 109.0],
#         ['10?', 403.0, 132.0],
#         ['5601', 402.0, 159.0],
#         ['6090', 374.0, 162.0],
#         ['6001', 335.0, 150.0],
#         ['5402', 344.0, 170.0],
#         ['5400', 334.0, 197.0],
#         ['5401', 294.0, 189.0],
#         ['5501', 264.0, 176.0],
#         ['5101', 224.0, 160.0],
#         ['5103', 264.0, 132.0],
#         ['5102', 293.0, 156.0],
#         ['5304', 365.0, 140.0],
#         ['5101', 224.0, 160.0],
#         ['5600', 403.0, 195.0],
#         ['5620', 402.0, 230.0],
#         ['5610', 377.0, 238.0],
#         ['5603', 361.0, 218.0],
#         ['5602', 335.0, 217.0],
#         ['5500', 261.0, 216.0],
#         ['5100', 224.0, 209.0],
#         ['6500', 195.0, 234.0],
#         ['6700', 155.0, 223.0],
#         ['xx01', 128.0, 206.0],
#         ['6701', 107.0, 224.0],
#         ['3244', 85.0, 230.0],
#         ['3245', 65.0, 214.0],
#         ['2210', 87.0, 180.0],
#         ['xx00', 34.0, 187.0],
#         ['7000', 21.0, 213.0],
#         ['xxxx', 14.0, 175.0],
#         ['7050', 14.0, 161.0],
#         ['3115', 52.0, 159.0],
#         ['3100', 86.0, 133.0],
#         ['xx00', 30.0, 126.0],
#         ['3020', 14.0, 109.0],
#         ['x300', 57.0, 97.0],
#         ['xxx0', 86.0, 97.0],
#         ['3500?', 72.0, 64.0],
#         ['8700', 45.0, 50.0],
#         ['xx5x', 132.0, 107.0],
#         ['3360', 143.0, 67.0],
#     ])
#     # sld_coords[:, 0] = sld_coords[:, 0]*4.72 - 431 + 394
#     coords[:, 1] = coords[:, 1]*-1 + 46 + 251.6  # *-4.72 + 954 + 148

#     return names, coords


def load():
    # geo_names, geo_coords = n44_coordinates()
    geo_names, geo_coords = n44_coordinates_sld(file='sld_geo.dxf')
    sld_names, sld_coords = n44_coordinates_sld(file='sld.dxf') 
    
    geo_names = np.array(geo_names)
    geo_coords = np.array(geo_coords)
    geo_coords[:, 1] /= 2
    sld_names = np.array(sld_names)
    sld_coords = np.array(sld_coords)

    geo_coords = geo_coords/15
    sld_coords = sld_coords/15
    
    # y_mean = np.mean(sld_coords[:, 1])
    # sld_coords[:, 1] = y_mean + (sld_coords[:, 1] - y_mean)*-1

    unique_names = np.unique(np.concatenate([geo_names, sld_names]))
    coords = np.zeros((len(unique_names), 4))*np.nan
    for i, name in enumerate(unique_names):
        # name = unique_names[5]
        lookup_idx = np.argwhere(name==geo_names)
        if len(lookup_idx) > 0:
            idx = lookup_idx[0][0]
            coords[i][0:2] = geo_coords[idx]

        lookup_idx = np.argwhere(name==sld_names)
        if len(lookup_idx) > 0:
            idx = lookup_idx[0][0]
            coords[i][2:4] = sld_coords[idx]

    return unique_names, coords


if __name__ == '__main__':
    print(n44_coordinates())
    print(n44_coordinates_sld())

    names, coords = load()

    print(names, coords)
    # _, coords = n44_coordinates_sld()
    import matplotlib.pyplot as plt
    plt.figure()
    plt.scatter(coords[:, 0], coords[:, 1])
    plt.gca().set_aspect(2)
    for n, c in zip(names, coords):
        plt.text(c[0], c[1], n)
    plt.show()

    plt.figure()
    plt.scatter(coords[:, 2], coords[:, 3])
    plt.gca().set_aspect(2)
    for n, c in zip(names, coords):

        plt.text(c[2], c[3], n)
    plt.show()
    # y_mean = np.mean(coords[:, 1])
    # plt.scatter(coords[:, 0],  y_mean + (coords[:, 1] - y_mean)*-1)
    # plt.show()