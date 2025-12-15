from pswamp import load_config
from pswamp.test_utils.runners import create_database


if __name__ == "__main__":
    config = load_config("../default_config.toml")
    # config = load_config()
    # config["single_line_diagrams"]

    create_database(config)
