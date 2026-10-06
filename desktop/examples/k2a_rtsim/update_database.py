from pswamp.test_utils.runners import create_database
from pswamp import load_config


if __name__ == '__main__':
    config = load_config()

    # runners.create_topics(config)
    # runners.publish_geo_data(config, load_coordinates())
    # runners.publish_model_data(config)

    create_database(config)