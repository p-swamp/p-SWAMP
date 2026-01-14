from pswamp.utils.load_config import load_config
from pswamp.visualization.fft_viz import fft_viz

if __name__ == '__main__':
    config = load_config('..')
    fft_viz(
        fft_window=5,
        kafka_topic=config['topics']['pmudata'],
        io_kwargs=config["streaming"],
    )