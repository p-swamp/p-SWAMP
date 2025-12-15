import pandas as pd
import ezdxf
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
import sys
from collections import defaultdict
from pswamp.visualization.components.single_line_diagram import get_buses, get_lines, get_branches_xy_by_matching_buses
import json
from pathlib import Path
__file__ = r'C:\Users\hallvarh\Coding\pswamp\pswamp\examples\nordic44_rtsim\data\read_sld_data.py'
current_dir = Path(__file__).parent

with open(current_dir/'model_data.json') as file:
    model_data = json.load(file)

model_data
model_data_lines = pd.DataFrame(
    columns=model_data['lines'][0], data=model_data['lines'][1:])

model_data_trafos = pd.DataFrame(
    columns=model_data['transformers'][0], data=model_data['transformers'][1:])


with open(current_dir / "sld.dxf") as file:
    dxf_file = file.read()
    
dxf_file
from io import StringIO
dxf_file_stream = StringIO(dxf_file)
doc = ezdxf.read(dxf_file_stream)
names, buses = get_buses(doc)
lines_xy, lines_midpoints = get_branches_xy_by_matching_buses(doc, model_data_lines)
trafos_xy, trafos_midpoints = get_branches_xy_by_matching_buses(doc, model_data_trafos)


len(lines_xy)
fig, ax = plt.subplots(1)
ax.scatter(buses[:, 0], buses[:, 1])
[ax.text(xy[0], xy[1], name) for xy, name in zip(buses, names)]
[ax.plot(xy[:, 0], xy[:, 1], color='b') for xy in lines_xy]
[ax.plot(xy[:, 0], xy[:, 1], color='r') for xy in trafos_xy]
# [ax.plot(line['xy'][:, 0], line['xy'][:, 1], color='gray') for line in branches_from_schematic]

# ax.plot(lines_xy[4][:, 0], lines_xy[4][:, 1], color='red')
plt.show()

len(lines_xy)
len(trafos_xy)
len(model_data_trafos)
from pprint import pprint
for xy, line in zip(lines_xy, model_data_lines.iterrows()):
    # print(len(xy))
    if len(xy) == 0:
        print(line)
[line for xy, line in zip(lines_xy, model_data_lines) if len(xy) == 0]
[len(xy) == 0 for xy in lines_xy]
    
    

# branches_from_schematic
# pprint(lines_xy)
