from pswamp import load_config
import json


def test_load_default_config():
    config = load_config()
    # with open(config['model_data_path']) as file:
        # model_data = json.load(file)

    # print(model_data)

if __name__ == '__main__':
    test_load_default_config()