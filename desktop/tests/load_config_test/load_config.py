import tomli
from pathlib import Path
from pprint import pprint
from pswamp.utils.load_config import load_config

if False:
    # # Config file in same dir as script:
    toml_dict = load_config()  # 'config.toml')
    # pprint(toml_dict)

    # # Config in relative dir:
    toml_dict = load_config('rel_dir')  # 'config.toml')
    # pprint(toml_dict)

    # # Config with specific name (e.g. specify full path)
    abs_path = Path(__file__).parent / 'config 2.toml'
    toml_dict = load_config(abs_path)  # 'config.toml')
    # pprint(toml_dict)

    abs_path = Path(__file__).parent
    toml_dict = load_config(abs_path)  # 'config.toml')
    # pprint(toml_dict)

    # Config with specific name in same dir as script:
    toml_dict = load_config('config 2.toml')  # 'config.toml')
    # pprint(toml_dict)
        
    # Config with specific name in relative dir:
    toml_dict = load_config('rel_dir/config 2.toml')  # 'config.toml')
    # pprint(toml_dict)

    # Path relative to project dir (for argparse)
    toml_dict = load_config('tests/load_config_test/config.toml')
    pprint(toml_dict)