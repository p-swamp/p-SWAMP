# LICENSE HEADER MANAGED BY add-license-header
#
# Copyright 2026 NTNU/SINTEF/Statnett SF
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

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
