import ezdxf
import matplotlib.pyplot as plt
import numpy as np
import time


def flatten_list_insert_nan(listlist):
    dim = listlist[0].shape[1]
    z = [*zip(listlist, [np.ones((1, dim)) * np.nan] * len(listlist))]
    flattened_list = [y for x in z for y in x]
    return np.vstack(flattened_list) if len(flattened_list) > 0 else np.empty((0, dim))


def load_dxf(path):
    doc = ezdxf.readfile(path)
    # fig, ax = plt.subplots(1)

    lines_hv = []
    lines_mv = []
    lines_lv = []
    for line in doc.query('LINE'):
        start = np.array(line.dxf.start)[:2]
        end = np.array(line.dxf.end)[:2]
        xyz = np.vstack([np.vstack([start, end]).T, np.zeros(2)]).T
        if line.dxf.layer == 'LV':
            lines_lv.append(xyz)
        elif line.dxf.layer == 'MV':
            lines_mv.append(xyz)
        else:
            lines_hv.append(xyz)

    lines = {
        'lines_hv': flatten_list_insert_nan(lines_hv)/15 if len(lines_hv) > 0 else np.zeros((0, 3)),
        'lines_mv': flatten_list_insert_nan(lines_mv)/15 if len(lines_mv) > 0 else np.zeros((0, 3)),
        'lines_lv': flatten_list_insert_nan(lines_lv)/15 if len(lines_lv) > 0 else np.zeros((0, 3)),
    }
    return lines