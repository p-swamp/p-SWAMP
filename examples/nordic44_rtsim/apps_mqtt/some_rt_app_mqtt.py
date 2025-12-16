from pswamp.utils.load_config import load_config
from pswamp.app_templates.time_window_app import TimeWindowApp
import numpy as np
import sys


class SomeRTApp(TimeWindowApp):
    """
    This is a simple example real-time application, analysing a time window of specified length, where the analysis
    is carried out in the "run_analysis" method.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run_analysis(self, t, phasors):
        # Currently just prints the "completeness" (in %) of the time window.
        sys.stdout.write(
            "\rTime window {:.2f}% complete".format(
                100 * (1 - (sum(np.isnan(t))) / len(t))
            )
        )
        return "Hei"


if __name__ == "__main__":
    config = load_config('../config_mqtt.toml')

    # Define the application
    from pswamp.streaming.mqtt_io import MQTT_IO
    io = MQTT_IO(
        mqtt_kwargs=config["mqtt"],
        input_topic="pmudata",
        output_topic="test_topic")

    app = SomeRTApp(
        io=io,
        window_length=10,
        # input_topic=config['topics']['pmudata'],
        # output_topic="test_topic",
        # command_topic=config['topics']['application.commands']
        # kafka_kwargs=config['kafka'],
    )

    # Run the application
    app.run()
