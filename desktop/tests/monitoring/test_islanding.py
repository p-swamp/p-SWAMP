from pswamp.utils.load_config import load_config
from nqkafka.utils import stop_server as stop_nqkafka_server
import pswamp.test_utils.runners as runners
from topsrt.sim import RealTimeSimulatorThread
from pswamp.test_utils.pmu_rtsim_to_kafka import PMUToKafkaPublisher
from pswamp.visualization.time_window_plot_v15 import run_time_window_plot
from pswamp.coordination.alarm_handling import AlarmSender
from pswamp.test_utils.sample_datasets.n44.sim import create_sim
from pswamp.test_utils.sample_datasets.n44.n44_rtsim_offline import run_n44_rtsim_offline, stop_case
from pswamp.monitoring.islanding import IslandingApp
from pswamp.test_utils.offline.topic_getter import TopicGetter
from pswamp.utils.misc import convert_time_stamp_to_seconds


def test_islanding(show_plots=False):
    
    config = load_config()
    config["streaming"]['bootstrap_servers'] = 'localhost:51005'
    config["streaming"]['consumers_seek_to_beginning'] = True

    events = [
        (20, ('line', 'L3244-6500', 'disconnect')),
        (20, ('line', 'L5100-6500', 'disconnect')),
        (20, ('line', 'L3115-6701', 'disconnect')),
        (20, ('line', 'L3701-6700', 'disconnect')),
        (40, ('line', 'L3244-6500', 'connect')),
        (40, ('line', 'L5100-6500', 'connect')),
        (40, ('line', 'L3115-6701', 'connect')),
        (40, ('line', 'L3701-6700', 'connect')),
    ]

    run_n44_rtsim_offline(config, events, t_end=70)
    app = IslandingApp(io_kwargs=config["streaming"], t_end=70)
    app.run()

    topic_data = {}
    for topic in config['topics']:
        print(f'Getting topic {topic}...')
        topic_data[topic] = TopicGetter(
            topic=topic, io_kwargs=config["streaming"],
            empty_topic_timeout=1).data

    alarm_time = convert_time_stamp_to_seconds(
        topic_data['alarms'][0].value['time_stamp'])
    alarm_time_end = convert_time_stamp_to_seconds(
        topic_data['alarms'][1].value['time_stamp'])

    assert alarm_time < 25
    assert alarm_time_end < 70
    
    if show_plots:
        import matplotlib.pyplot as plt
        import numpy as np
        freq = np.array([msg.value.get_freq() for msg in topic_data['pmudata']])
        time_stamp = np.array([msg.value.get_time_stamp() for msg in topic_data['pmudata']])
        plt.plot(time_stamp, freq)
        plt.axvline(alarm_time, color='r')
        plt.axvline(alarm_time_end, color='r')
        plt.show()
    
    
    stop_case(config)


if __name__ == '__main__':
    test_islanding(show_plots=True)