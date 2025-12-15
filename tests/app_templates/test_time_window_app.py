from pswamp.test_utils.sample_datasets.mock_case import run_mock_case, stop_mock_case
from pswamp import load_config
from pswamp.app_templates.time_window_app import TimeWindowApp
from pswamp.test_utils.sample_datasets.n44.sim import create_sim
import time
from pswamp.test_utils.offline.rtsim_adapter import PMUPublisherMod
from tops.simulator import Simulator


def test_app_online():
    config = load_config()
    config['kafka']['bootstrap_servers'] = 'localhost:51000'
    config['kafka']['consumers_seek_to_beginning'] = True
    run_mock_case(config)
    time.sleep(1)
    app = TimeWindowApp(
        kafka_kwargs=config['kafka'],
        report_status=True,
        t_end=10)
    
    stop_mock_case(config)

def test_app_offline_rtsim():
    ps = create_sim()
    sim = Simulator(ps, t_end=10)
    sim.interface_quitters = {}
    pmus = PMUPublisherMod(sim)
    app = TimeWindowApp(io=pmus, t_end=1)
    # app.update_callbacks.append(lambda: print(app.most_recent_time_stamp))
    app.run()


if __name__ == '__main__':
    test_app_online()
    test_app_offline_rtsim()