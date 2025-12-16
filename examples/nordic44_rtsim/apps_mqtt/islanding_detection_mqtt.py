from pswamp.monitoring.islanding import IslandingApp
from pswamp import load_config
from pswamp.streaming.mqtt_io import MQTT_IO

if __name__ == "__main__":

    # Define the application
    config = load_config('../config_mqtt.toml')
    io = MQTT_IO(
        mqtt_kwargs=config["mqtt"],
        input_topic="pmudata",
        output_topic="islanding")

    app = IslandingApp(
        io=io,
        window_length=20,
        mean_threshold=0.1,
        # input_topic=config['topics']['pmudata'],
        # output_topic=config['topics']['islanding'],
        # kafka_kwargs=config['kafka'],
        eval_freq=1,
    )

    # Run the application
    app.run()