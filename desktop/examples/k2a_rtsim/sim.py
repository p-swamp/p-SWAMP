from pathlib import Path
import json
import tops.dynamic as dps


import multiprocessing as mp
from topsrt_random_load_variations import RandomLoadVariations, remove_model_data
# import ieee39_model as model_data

def create_sim():

    # model = model_data.load()
    # rows = []
    # for target_load in ['L5610-1']:  # , 'L6700-mod']:
    #     target_load_idx = np.argwhere([row[0] == target_load for row in model['loads']])[0][0]
    #     row = model['loads'].pop(target_load_idx)
    #     rows.append([row[0],     0.1,        1,    row[1],     0.1,           0.1,       0.1,       0.1,        -row[2],      -row[3]])
    
    # model['vsc'] = {'VSC': [
    #     ['name',    'T_pll',    'T_i',  'bus',  'P_K_p',    'P_K_i',    'Q_K_p',    'Q_K_i',    'P_setp',   'Q_setp'],
    #     *rows
    # ]}
    
    with open(str(Path(__file__).parent/'data/model_data.json')) as f:
        data = f.read()
    model = json.loads(data)
    model["buses"] = model.pop("bus")
    model["lines"] = model.pop("line")
    model["trafos"] = model.pop("trafo")
    model["loads"] = model.pop("load")
    keys = list(model.keys())
    for key in keys:
        spl = key.split(":")
        if len(spl) <= 1:
            continue
        model[spl[0]] = {spl[1]: model.pop(key)}    

    ps = dps.PowerSystemModel(model=model)  # "examples/k2a_rtsim/data/model_data.json")

    ps.add_model_data({"loads": {
        "DynamicLoadFiltered": [
            [*ps.loads["Load"].par.dtype.names, "T_g", "T_b"],
            *[[*load_data, 5, 5] for load_data in ps.loads["Load"].par],
        ]}
    })
    remove_model_data(ps, "loads", "Load")

    if not hasattr(ps, 'pll'):
        ps.add_model_data({'pll':{
            'PLL1': [
                ['name',        'T_filter',     'bus'   ],
                *[[f'PLL{i}',    0.1,            bus_name  ] for i, bus_name in enumerate(ps.buses['name'])],
            ],
            'PLL2': [
                ['name',        'K_p',  'K_i',  'bus'   ],
                *[[f'PLL{i}',    10,     1,      bus_name  ] for i, bus_name in enumerate(ps.buses['name'])],
            ]
        }})
    
    ps.init_dyn_sim()

    # ps.ode_fun(0, ps.x0)
    return ps


if __name__ == "__main__":
    ps = create_sim()
    ps.init_dyn_sim()