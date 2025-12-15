import numpy as np
import tops.dynamic as dps
from pathlib import Path


def create_sim():
    ps = dps.PowerSystemModel(model=str(Path(__file__).parent/'model_data.json'))

    control_data = {}
    control_data['gov'] = {'TGOV1':
                        [['name', 'gen', 'R', 'D_t', 'V_min', 'V_max', 'T_1', 'T_2', 'T_3']] +
                        [['GOV' + str(i), name, 0.05, 0, 0, 1, 0.2, 1, 2] for i, name in
                         enumerate(ps.gen['GEN'].par['name'])]
                    }

    control_data['avr'] = {'SEXS':
                        [['name', 'gen', 'K', 'T_a', 'T_b', 'T_e', 'E_min', 'E_max']] +
                        [['AVR' + str(i), name, 100, 2.0, 10.0, 0.5, -3, 3] for i, name in
                         enumerate(ps.gen['GEN'].par['name'])]
                    }

    control_data['pss'] = {'STAB1':
                        [['name', 'gen', 'K', 'T', 'T_1', 'T_2', 'T_3', 'T_4', 'H_lim']] +
                        [['PSS' + str(i), name, 50, 10.0, 0.5, 0.5, 0.05, 0.05, 0.03] for i, name in
                         enumerate(ps.gen['GEN'].par['name'])]
                    }
    
    ps.add_model_data(control_data)

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


if __name__ == '__main__':
    ps = create_sim()