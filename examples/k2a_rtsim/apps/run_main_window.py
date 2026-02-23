from pswamp.gui.main_window import run_main_window
from pswamp import load_config

if __name__ == '__main__':
    config = load_config("..")
    run_main_window(config, activate_default_layers=False)
