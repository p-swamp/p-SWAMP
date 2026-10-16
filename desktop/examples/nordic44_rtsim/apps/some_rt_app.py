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


if __name__ == "__main__":
    config = load_config('..')

    # Define the application
    app = SomeRTApp(
        window_length=10,
        input_topic=config['topics']['pmudata'],
        io_kwargs=config["streaming"],
    )

    # Run the application
    app.run()
