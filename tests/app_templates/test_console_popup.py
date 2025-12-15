from pswamp.app_templates.snapshot_app import SnapshotApp
from pswamp.test_utils.sample_datasets.n44_mock_case import run_mock_case,\
    stop_mock_case  # , generate_pmu_cfg_from_model, DataFrameGenerator
    
import numpy as np
import sys
from pswamp.streaming.kafka_extras import KafkaProducer


class SomeRTApp(SnapshotApp):
    def run_analysis(self, time_stamp, measurements):
        sys.stdout.write(f"\r{time_stamp:.2f}")
        # sys.stdout.write("\rTime window {:.2f}% complete".format(100 * (1 - (sum(np.isnan(time_stamp))) / len(time_stamp))))



if __name__ == '__main__':
    from pswamp import load_config
    import time
    config = load_config()
    config['topics']['application.commands'] = 'application.commands'
    config['kafka']['consumers_seek_to_beginning'] = True
    config['kafka']['bootstrap_servers'] = 'localhost:51002'
        
    run_mock_case(config, t_end=10)

    app = SomeRTApp(kafka_kwargs=config['kafka'])

    def issue_command():
        producer = KafkaProducer(**config['kafka'])
        time.sleep(2)
        producer.send('application.commands', {'target_uuid': app.uuid, 'command': 'open_console'})

        time.sleep(5)
        producer.send('application.commands', {'target_uuid': app.uuid, 'command': 'stop'})

    import threading
    command_thread = threading.Thread(target=issue_command)
    command_thread.start()

    
    app.start()




    stop_mock_case(config)

    # cfg = generate_pmu_cfg_from_model(config)

    # data_frame = DataFrameGenerator.generate_data_frame(cfg)
    # len(np.concatenate(data_frame.get_phasors()))
    # len(data_frame.get_freq())*2    