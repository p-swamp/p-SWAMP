from pswamp.utils.load_config import load_config
from nqkafka.utils import stop_server as stop_nqkafka_server
from data.coords import load as load_coordinates
import pswamp.test_utils.runners as runners
from topsrt.sim import RealTimeSimulatorThread
from pswamp.test_utils.pmu_rtsim_to_kafka import PMUToKafkaPublisher
from pswamp.visualization.time_window_plot_v15 import run_time_window_plot
from pswamp.coordination.alarm_handling import AlarmSender


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



def run_n44_mock_case(config, events=None):
    config = load_config()
    config['kafka']['consumers_seek_to_beginning'] = True

    if config['kafka']['use_nqkafka']:
        runners.run_nqkafka_server(config, run_in_process=False)
        print('Started NQKafka Server')
    
    # Wait for a while, to make sure the server has started before continuing
    # time.sleep(2)

    runners.create_topics(config)
    runners.publish_geo_data(config, load_coordinates())
    runners.publish_model_data(config)

    from sim import create_sim
    ps = create_sim()

    events = Events([
        (1, ('line', 'L3359-5101-1', 'disconnect')),
        (1.2, ('line', 'L3359-5101-1', 'connect')),
    ])
    
    rts = RealTimeSimulatorThread(ps, dt=10e-3, t_end=10, speed=10)
    rts.interface_functions['printer'] = lambda rts: print(rts.sol.t)
    rts.interface_functions['Events'] = events.update
    
    pmus = PMUToKafkaPublisher(rts=rts, **{'topic': 'pmudata', 'kafka_kwargs': config['kafka']})
    pmus.start()
    rts.run()

    alarm_sender = AlarmSender(kafka_kwargs=config['kafka'])
    alarm_sender.start()


if __name__ == '__main__':
    

    run_time_window_plot(config)

    stop_mock_case(config)