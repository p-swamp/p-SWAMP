import tomli
from pathlib import Path
import inspect


def get_calling_file_path():
    modules = [inspect.getmodule(s[0]) for s in inspect.stack()]
    try:
        main_module = next(
            m for m in modules if m is not None and m.__name__ == '__main__')
    except StopIteration:
        main_module = None
        
    return Path(
        main_module.__file__
    ).parent if main_module is not None else Path('')


def load_config(arg=None):
    """Load pswamp configuration file, usually named config.toml.

    Input argument determines where to look for the configuartion file.
    
    If no arguments are specified: First, try to look for a file named
    "config.toml" in the same folder as the running script. If this is not
    found, load the default config (which is located in
    pswamp/test_utils/default_config.toml).

    TODO: Describe what happens if arguments are specified. In general, the
    input argument is a path, e.g., load_config('..') means "try to find
    config.toml in the folder one level up from the script". The argument can
    also be the full (absolute) path to a config.toml file.

    Once the file has been loaded, it will resolve any paths in the file, so
    that files can be loaded.

    If there is an "include" field in the config.toml, files specified here will
    be merged with the main configuration file.
    
    Args:
        arg: Specifies where to look for configuration file.
    """

    # If it is a dict: Return the dict.
    if isinstance(arg, dict):
        return arg

    if arg is None:
        # Check if config file is found in path of calling file
        if (get_calling_file_path()/'config.toml').is_file():
            config_file_path = get_calling_file_path()/'config.toml'
        # If not: Use default config
        else:
            print('Config file not found, using default config.')
            config_file_path = Path(__file__).parent.parent / 'test_utils' / 'default_config.toml'
    
    elif str(arg)[-5:] == '.toml' and Path(arg).is_file():
        config_file_path = Path(arg)

    elif str(arg)[-5:] == '.toml' and (get_calling_file_path()/arg).is_file():
        config_file_path = get_calling_file_path()/arg
    
    elif Path(arg).is_dir() and (Path(arg)/'config.toml').is_file():
        config_file_path = Path(arg)/'config.toml'
    
    elif (get_calling_file_path()/arg/'config.toml').is_file():
        config_file_path = get_calling_file_path()/arg/'config.toml'
        
    else:
        raise FileNotFoundError('Could not find config file.')

    project_dir_path = config_file_path.parent
    
    with config_file_path.open("rb") as f:
        toml_dict = tomli.load(f)

    # Add any included toml files to the main one
    if 'include' in toml_dict:
        for include_file in toml_dict['include']:
            with (project_dir_path / include_file).open("rb") as f:
                toml_dict_include = tomli.load(f)
            toml_dict = {**toml_dict, **toml_dict_include}
    

    # Loop through all entries. For those with "_path" in the name, full/absolute paths are substituted.
    toml_dict_out = toml_dict.copy()
   
    def recursive_substitute(toml_dict):
        for key, val in toml_dict.items():
            if isinstance(key, str) and '_path' in key:
                toml_dict[key] = project_dir_path / Path(val)
            elif isinstance(val, dict):
                recursive_substitute(val)
    
    recursive_substitute(toml_dict_out)
    
    return toml_dict_out


if __name__ == '__main__':
    print(load_config())