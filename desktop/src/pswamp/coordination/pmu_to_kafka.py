# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from synchrophasor.pdc import Pdc
from synchrophasor.frame import DataFrame
from pswamp.streaming import Producer


class PMUToKafka:
    """This class receives PMU data (using PyPMU) and forwards the full dataframes to a specified Kafka topic."""

    def __init__(
        self,
        pdc_id,
        pmu_ip,
        pmu_port,
        io_kwargs,
        kafka_topic="pmudata",
    ):
        """Constructor for PMU receiver. Specify id, ip and port of the PDC.

        Args:
            pdc_id: id of the PDC .
            pmu_ip: ip of the PDC.
            pmu_port: port of the PDC.
        """
        self.pdc = Pdc(pdc_id=pdc_id, pmu_ip=pmu_ip, pmu_port=pmu_port)
        self.pdc.logger.setLevel("DEBUG")
        self.subscribers = []
        self.header = None
        self.config = None
        self._stopped = False

        self.kafka_topic = kafka_topic
        self.kafka_producer = Producer(**io_kwargs)

    def connect_to_pmu(self):
        """Connect to the PDC, and receive header- and configuration frames. Does not start stream of data.
        Returns:
            None

        """
        self.pdc.run()  # Connect to PMU
        self.pdc.stop()
        self.config = self.pdc.get_config()
        #self.pdc.start()

    def run(self):
        """Ask PDC to start sending data and start receiving and forwarding data."""

        self.pdc.start()  # Request to start sending measurements
        while not self._stopped:

            data = self.pdc.get()  # Keep receiving recorded_pmu_data_raw
            if isinstance(data, DataFrame):
                self.kafka_producer.send(self.kafka_topic, data)
                self.kafka_producer.flush()

            elif data is None:
                print('Not data')
                # pdc.quit()  # Close connection
                # break
            elif isinstance(data, list):
                for data_ in data:
                    self.kafka_producer.send(self.kafka_topic, data_)
                    self.kafka_producer.flush()
