from pswamp.gui.main_window import run_main_window
from pswamp import load_config

if __name__ == '__main__':
    config = load_config("../config_no.toml")
    config["streaming"]['consumers_seek_to_beginning'] = True
    config["other_tso"][0]["streaming"]['consumers_seek_to_beginning'] = True
    run_main_window(config)
