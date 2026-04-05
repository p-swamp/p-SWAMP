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

import numpy as np
from pswamp.utils.misc import lookup_strings

# Get buses

SCALING_FACTOR = 1/15


def get_buses(doc, bus_names_model=None):
    texts = doc.query('MTEXT')
    names = np.array([text.dxf.text for text in texts])
    x = np.array([text.dxf.insert.x for text in texts])
    y = np.array([text.dxf.insert.y for text in texts])
    buses = np.vstack([x, y]).T
    buses = np.round(2*buses)/2

    if bus_names_model is not None:
        sort_idx = lookup_strings(bus_names_model, names)
        names, buses = names[sort_idx], buses[sort_idx]

    return names, buses*SCALING_FACTOR


def get_line_segments(doc):
    line_starts = np.array([(line.dxf.start.x, line.dxf.start.y)
                           for line in doc.query('LINE')])
    line_ends = np.array([(line.dxf.end.x, line.dxf.end.y)
                         for line in doc.query('LINE')])
    line_starts = np.round(2*line_starts)/2
    line_ends = np.round(2*line_ends)/2

    return line_starts*SCALING_FACTOR, line_ends*SCALING_FACTOR


def draw_line_from_to(line_start, line_end):
    return [line_start[0], line_end[0]], [line_start[1], line_end[1]]


def connected(point, points, covered=None, threshold=1e-3):
    if covered is None:
        covered = np.zeros(len(points), dtype=bool)
    new_hit = (np.linalg.norm(point - points, axis=1) < threshold)*~covered

    if np.any(new_hit):
        return np.argwhere(new_hit).flatten()
    else:
        return np.array([])


def recursive_search(point, line_starts, line_ends, covered, stoppers, first_call=False, threshold=1e-3):
    point_in_stoppers = np.any(np.linalg.norm(
        point - stoppers, axis=1) < threshold)
    if point_in_stoppers and not first_call:
        return [], []

    connected_lines = []
    directions = []
    for line_idx in connected(point, line_starts, covered, threshold):
        connected_lines.append(line_idx)
        directions.append(True)
        covered[line_idx] = True
        new_connected_lines, new_directions = recursive_search(
            line_ends[line_idx, :], line_starts, line_ends, covered, stoppers)
        [connected_lines.append(n) for n in new_connected_lines]
        [directions.append(d) for d in new_directions]

    for line_idx in connected(point, line_ends, covered, threshold):
        connected_lines.append(line_idx)
        directions.append(False)
        covered[line_idx] = True
        new_connected_lines, new_directions = recursive_search(
            line_starts[line_idx, :], line_starts, line_ends, covered, stoppers)
        [connected_lines.append(n) for n in new_connected_lines]
        [directions.append(d) for d in new_directions]

    return connected_lines, directions


def get_lines(doc):
    bus_names, buses = get_buses(doc)
    # Get line segments
    line_starts, line_ends = get_line_segments(doc)
    covered = np.zeros(len(line_starts), dtype=bool)
    i = 0
    lines = []
    for bus in buses:
        for line_idx_0 in connected(bus, line_starts):
            if covered[line_idx_0]:
                continue
            covered[line_idx_0] = True
            direction_0 = True
            line_idx, directions = recursive_search(
                line_ends[line_idx_0], line_starts, line_ends, covered, buses, first_call=False, threshold=1e-3)
            line = ([line_idx_0] + line_idx), ([direction_0] + directions)
            lines.append(line)
        for line_idx_0 in connected(bus, line_ends):
            if covered[line_idx_0]:
                continue
            covered[line_idx_0] = True
            direction_0 = False
            line_idx, directions = recursive_search(
                line_starts[line_idx_0], line_starts, line_ends, covered, buses, first_call=False, threshold=1e-3)
            line = ([line_idx_0] + line_idx), ([direction_0] + directions)
            lines.append(line)

    line_idx, dirs = lines[0]

    full_lines = []
    for line_idx, dirs in lines:
        line_idx = np.array(line_idx)
        dirs = np.array(dirs)
        points = line_starts[line_idx]*dirs[:, None] + \
            line_ends[line_idx]*~dirs[:, None]
        last_point = line_ends[line_idx[-1]] * \
            dirs[-1] + line_starts[line_idx[-1]]*~dirs[-1]
        xy = np.vstack([points, last_point])
        from_bus_search = connected(xy[0, :], buses)
        to_bus_search = connected(xy[-1, :], buses)
        from_bus = bus_names[from_bus_search[0]] if len(
            from_bus_search) > 0 else None
        to_bus = bus_names[to_bus_search[0]] if len(
            to_bus_search) > 0 else None

        segment_lengths = np.sqrt(np.sum((xy[1:, :] - xy[:-1, :])**2, axis=1))
        target_length = sum(segment_lengths) / 2
        segment_idx = np.argmax(np.cumsum(segment_lengths) > target_length)
        share = (target_length - np.sum(segment_lengths[:segment_idx]))/segment_lengths[segment_idx]
        midpoint = xy[segment_idx] + share*(xy[segment_idx + 1] - xy[segment_idx])

        full_lines.append({'from': from_bus, 'to': to_bus, 'xy': xy, 'midpoint': midpoint})

    return full_lines


def get_branches_xy_by_matching_buses(doc, model_data):
    branches_from_schematic = get_lines(doc)
    lines_xy = []
    midpoints = []
    for f, t in zip(model_data['from_bus'], model_data['to_bus']):
        found = False
        for i, line in enumerate(branches_from_schematic):
            if (line['from'] == f and line['to'] == t):
                reversed = False
            elif (line['from'] == t and line['to'] == f):
                reversed = True
            else:
                continue

            # print(line['from'], line['to'], f, t, reversed)
            line_match = branches_from_schematic.pop(i)
            line_match
            lines_xy.append(
                np.flipud(line_match['xy']) if reversed else line_match['xy'])
            midpoints.append(line['midpoint'])
            found = True
            break

        if not found:
            lines_xy.append(np.zeros((0, 2)))
            midpoints.append(np.nan*np.zeros(2))

    return lines_xy, midpoints
