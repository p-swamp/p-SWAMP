import threading
from nqkafka.server import NQKafkaServer
from pswamp.streaming import Producer
from synchrophasor.timeSeriesPlayback import PMUTimeSeriesPublisher
from pswamp.coordination.pmu_to_kafka import PMUToKafka
from pswamp.test_utils.pmu_csv_to_kafka import CSVtoKafka
from pswamp.streaming.base import create_topic
from pswamp.utils.load_config import load_config
from pswamp.test_utils.csv_playback.kafka_streamer import PMUDataStreamerKafka
import json
from pswamp.models.reader import replace_data_lists_with_dataframes
from pswamp.streaming.utils import encoder

import sqlite3
import pandas as pd


def run_nqkafka_server(*config_args, run_in_process=True):
    config = load_config(*config_args)
    # Start NQKafka Server
    server = NQKafkaServer(config["streaming"]['bootstrap_servers'],
                           run_in_process=run_in_process)
    server.start()


def create_topics(*config_args, n_samples=6000):
    config = load_config(*config_args)
    # Create topics:
    for topic in config['topics']:
        create_topic(name=topic, io_kwargs=config["streaming"], n_samples=n_samples)


def publish_geo_data(config, data, kafka_topic='pmu.coords'):
    io_kwargs = config["streaming"]
    
    bus_names, bus_coords = data

    kafka_producer = Producer(**io_kwargs)
    kafka_producer.send(kafka_topic, [bus_names, bus_coords])
    kafka_producer.flush()


def publish_model_data(config, kafka_topic='model.data'):
    io_kwargs = config["streaming"]

    data = {}
    if 'model_data_path' in config:
        with open(config['model_data_path']) as file:
            data['model'] = json.load(file)
    
    if 'sld_data' in config and 'line_data_path' in config['sld_data']:
        with open(config['sld_data']['line_data_path']) as file:
            data['schematics'] = file.read()

    kafka_producer = Producer(**io_kwargs)
    kafka_producer.send(kafka_topic, data)
    kafka_producer.flush()

def csv_to_c37118(config, data, ip=None, port=50000):
    if ip is None:
        import socket
        ip = socket.gethostbyname(socket.gethostname())  # Get local ip automatically
        port = 50000

    # PMU Snapshot Publisher
    pmu_publisher = PMUTimeSeriesPublisher(
        ip,
        port,
        time=data['time'],
        # publish_frequency=10,  # is determined automatically if not specified
        phasors=data['phasors'],
        station_names=data['stations'],
        channel_names=data['channels'],
    )
    pmu_publisher.pmu.run()  # Start listening to incoming connections and send data (if published)
    pmu_publisher.main_loop()


def c37118_to_kafka(config, ip=None, port=50000, pdc_id=1410, kafka_topic='pmudata', kafka_topic_meta="pmudata.meta"):

    if ip is None:
        import socket
        ip = socket.gethostbyname(socket.gethostname())  # Get local ip automatically
        port = 50000
    
    # Define PMU receiver
    pmu_to_kafka = PMUToKafka(
        pdc_id=pdc_id,
        pmu_ip=ip,
        pmu_port=port,
        io_kwargs=config["streaming"],
        kafka_topic=config['topics']['pmudata'],
        # kafka_topic_meta=config['topics']["pmudata.meta"],
    )

    pmu_to_kafka.connect_to_pmu()
    pmu_to_kafka.run()


def csv_to_kafka(config, data, speed=1, t_end=None, show_playback_control=False):

    pmu_publisher = CSVtoKafka(
        io_kwargs=config["streaming"],
        topic=config['topics']['pmudata'],
        time=data['time'],
        # publish_frequency=10,  # is determined automatically if not specified
        phasors=data['phasors'],
        station_names=data['stations'],
        channel_names=data['channels'],
        freq_data=data['frequency'] if 'frequency' in data else None,
        dfreq_data=data['dfrequency'] if 'dfrequency' in data else None,
        speed=speed,
        t_end=t_end,
    )
    pmu_publisher.initialize()
    # pmu_publisher.main_loop()
    pmu_publisher_thread = threading.Thread(target=pmu_publisher.main_loop)
    pmu_publisher_thread.start()

    if show_playback_control:
        from pswamp.test_utils.csv_playback.playback_gui import run_simulation_control
        run_simulation_control(pmu_publisher)


def csv_to_kafka_2(config, data_path, speed=1, n_samples=None, streamer_class=PMUDataStreamerKafka, show_playback_control=False, **kwargs):

    pmu_publisher = streamer_class(
        publisher_kwargs={'topic': config['topics']['pmudata'], **config["streaming"]},
        pmu_data_folder=data_path,
        speed=speed,
        n_samples=n_samples,
        # t_end=t_end,
        **kwargs
    )
    # pmu_publisher.initialize()
    pmu_publisher_thread = threading.Thread(target=pmu_publisher.main_loop)
    pmu_publisher_thread.start()
    # pmu_publisher.main_loop()

    if show_playback_control:
        from pswamp.test_utils.csv_playback.playback_gui import run_simulation_control
        run_simulation_control(pmu_publisher)


def create_database(*config_args):
    config = load_config(*config_args)

    data = {}
    if 'model_data_path' in config:
        with open(config['model_data_path']) as file:
            model_data = json.load(file)
        replace_data_lists_with_dataframes(model_data)
        data["model"] = model_data
        
    # if 'sld_data' in config and 'line_data_path' in config['sld_data']:
    #     with open(config['sld_data']['line_data_path']) as file:
    #         data['graphics'] = file.read()

    if 'single_line_diagrams' in config:
        sld_data = {}
        for name, sld_data_ in config['single_line_diagrams'].items():
            with open(sld_data_["data_path"]) as file:
                sld_data[name] = file.read()

            # sld_data[name] = sld_data_

        data["single_line_diagrams"] = sld_data
    
            

    if config["database"]["type"] == "sqlite":
        print(f"{config['database']['file_path']}")
        con = sqlite3.connect(f"{config['database']['file_path']}")
        for key, val in data["model"].items():
            if isinstance(val, pd.DataFrame):
                try:
                    val.to_sql(key, con)
                except ValueError:
                    continue

        sld_data = data["single_line_diagrams"]

        cursor = con.cursor()        
        try:
            cursor.execute("""CREATE TABLE "single_line_diagrams" ("name" TEXT, "data"	BLOB);""")
        except sqlite3.OperationalError:
            pass

        for key, val in sld_data.items():
            try:
                cursor.execute(f"""INSERT INTO "single_line_diagrams" (name, data) VALUES ('{key}', '{val}')""")
                con.commit()
            except sqlite3.OperationalError:
                pass


def run_apps(config):
    ...