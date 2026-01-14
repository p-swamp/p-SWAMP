from pswamp.monitoring.islanding import IslandingApp
from pswamp import load_config

if __name__ == "__main__":

    # Define the application
    config = load_config('..')
    app = IslandingApp(
        window_length=20,
        mean_threshold=0.1,
        input_topic=config['topics']['pmudata'],
        output_topic=config['topics']['islanding'],
        io_kwargs=config["streaming"],
        eval_freq=1,
    )

    # Run the application
    app.run()