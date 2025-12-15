from pswamp.utils.load_config import load_config
from nqkafka.utils import stop_server as stop_nqkafka_server
import pswamp.test_utils.runners as runners
from topsrt.sim import RealTimeSimulatorThread
from pswamp.test_utils.pmu_rtsim_to_kafka import PMUToKafkaPublisher
from pswamp.visualization.time_window_plot_v15 import run_time_window_plot
from pswamp.coordination.alarm_handling import AlarmSender
from pswamp.test_utils.sample_datasets.n44.sim import create_sim

import numpy as np


class Events:
    def __init__(self, data):
        self.data = data
        self.next_event_time = None
        self.next_event_data = None

    def update(self, sim):
        if len(self.data) == 0 and self.next_event_time is None:
            # Could be stopped
            return
        
        if self.next_event_time is None:
            self.next_event_time, self.next_event_data = self.data.pop(0)

        if self.next_event_time <= sim.sol.t:
            if self.next_event_data[0] == 'line':
                sim.ps.lines['Line'].event(sim.ps, self.next_event_data[1], self.next_event_data[2])
            self.next_event_time = None



def run_n44_rtsim_offline(config, events_spec=None, t_end=10):

    if config['kafka']['use_nqkafka']:
        runners.run_nqkafka_server(config, run_in_process=False)
        print('Started NQKafka Server')
    
    # Wait for a while, to make sure the server has started before continuing
    # time.sleep(2)

    # runners.create_topics(config)
    # runners.publish_geo_data(config, load_coordinates())
    runners.publish_model_data(config)

    ps = create_sim()
    
    rts = RealTimeSimulatorThread(ps, dt=10e-3, t_end=t_end, speed=np.inf)
    # rts.interface_functions['printer'] = lambda rts: print(rts.sol.t)
    if events_spec is not None:
        events = Events(events_spec)
        rts.interface_functions['Events'] = events.update
    
    pmus = PMUToKafkaPublisher(rts=rts, **{'topic': 'pmudata', 'kafka_kwargs': config['kafka']})
    pmus.start()
    rts.run()




def stop_case(config):
    from nqkafka.utils import stop_server
    stop_server(config['kafka']['bootstrap_servers'])

if __name__ == '__main__':
    
    from pswamp.monitoring.islanding import run_islanding_application
    
    config = load_config()
    config['kafka']['consumers_seek_to_beginning'] = True

    # events = [
    #     (1, ('line', 'L3359-5101-1', 'disconnect')),
    #     (1.2, ('line', 'L3359-5101-1', 'connect')),
    # ]

    events = [
        (1, ('line', 'L3244-6500', 'disconnect')),
        (1, ('line', 'L5100-6500', 'disconnect')),
        (1, ('line', 'L3115-6701', 'disconnect')),
        (1, ('line', 'L3701-6700', 'disconnect')),
        (10, ('line', 'L3244-6500', 'connect')),
        (10, ('line', 'L5100-6500', 'connect')),
        (10, ('line', 'L3115-6701', 'connect')),
        (10, ('line', 'L3701-6700', 'connect')),  
    ]

    run_n44_rtsim_offline(config, events, t_end=20)
    run_islanding_application(config, t_end=20)
    run_time_window_plot(config)
    stop_case(config)