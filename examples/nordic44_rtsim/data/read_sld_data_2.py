import matplotlib.pyplot as plt
from pathlib import Path
# from pswamp.visualization.components.single_line_diagram import get_buses, get_lines, get_xy_by_matching_buses
from pswamp.utils.single_line_diagram import load_dxf
from pathlib import Path
current_dir = Path(__file__).parent


data = load_dxf(current_dir /"sld_geo.dxf")

plt.plot(data['lines_hv'][:, 0], data['lines_hv'][:, 1], 'r')
plt.plot(data['lines_mv'][:, 0], data['lines_mv'][:, 1], 'b')
plt.plot(data['lines_lv'][:, 0], data['lines_lv'][:, 1], 'g')
plt.show()