from pswamp.monitoring.n4sid import N4SIDApp
import threading
import numpy as np
import time
from pswamp.utils.load_config import load_config

if __name__ == "__main__":

    config = load_config('..')
    sid = N4SIDApp(
        window_length=120,
        input_topic=config['topics']["pmudata"],
        output_topic=config['topics']["modeestimation"],
        sys_order=10,
        kafka_kwargs=config['kafka'],
    )

    sid_thread = threading.Thread(target=sid.run, daemon=True)
    sid_thread.start()

    while True:
        time.sleep(1)
        print(sid.eigs[0].imag / (2 * np.pi))
