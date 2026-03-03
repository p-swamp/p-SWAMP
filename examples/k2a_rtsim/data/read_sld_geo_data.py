import json
from io import StringIO
from pathlib import Path

import ezdxf
import matplotlib.pyplot as plt
import pandas as pd

from pswamp.visualization.components.single_line_diagram import (
    get_branches_xy_by_matching_buses,
    get_buses,
    # get_lines,
)

# __file__ = r'examples\k2a_rtsim\data\read_sld_geo_data.py'
current_dir = Path(__file__).parent

with open(current_dir/'model_data.json') as file:
    model_data = json.load(file)

model_data
model_data_lines = pd.DataFrame(
    columns=model_data['line'][0], data=model_data['line'][1:])

model_data_trafos = pd.DataFrame(
    columns=model_data['trafo'][0], data=model_data['trafo'][1:])


with open(current_dir / "sld.dxf") as file:
    dxf_file = file.read()
    
dxf_file
dxf_file_stream = StringIO(dxf_file)
doc = ezdxf.read(dxf_file_stream)
names, buses = get_buses(doc)
lines_xy, lines_midpoints = get_branches_xy_by_matching_buses(doc, model_data_lines)
trafos_xy, trafos_midpoints = get_branches_xy_by_matching_buses(doc, model_data_trafos)


len(lines_xy)
fig, ax = plt.subplots(1)
ax.set_aspect(1)
ax.scatter(buses[:, 0], buses[:, 1])
[ax.text(xy[0], xy[1], name) for xy, name in zip(buses, names)]
[ax.plot(xy[:, 0], xy[:, 1], color='b') for xy in lines_xy]
[ax.plot(xy[:, 0], xy[:, 1], color='r') for xy in trafos_xy]

plt.show()

# len(lines_xy)
# len(trafos_xy)
# len(model_data_trafos)
# for xy, line in zip(lines_xy, model_data_lines.iterrows()):
#     # print(len(xy))
#     if len(xy) == 0:
#         print(line)
# [line for xy, line in zip(lines_xy, model_data_lines) if len(xy) == 0]
# [len(xy) == 0 for xy in lines_xy]