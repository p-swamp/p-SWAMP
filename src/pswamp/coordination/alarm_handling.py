# LICENSE HEADER MANAGED BY add-license-header
#
# Copyright 2026 NTNU/SINTEF/Statnett SF
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import threading
from pswamp.streaming import Producer, Consumer
import datetime
import uuid
from collections import OrderedDict


class AlarmSender:
    """Application for sending alarms, based on status of running WAMPAC apps
    
    Consumes messages from the 
    """
    def __init__(
        self,
        io_kwargs,
        input_topic='application.status',
        alarm_topic='alarms',
        alarm_time_threshold=15,
    ):

        self.input_topic = input_topic
        self.alarm_topic = alarm_topic
        self.io_kwargs = io_kwargs

        self.input_stream = Consumer(
            input_topic, **io_kwargs
        )

        self.output_stream = Producer(**io_kwargs
        )

        self.app_status = dict()
        self.alarm_time_threshold = alarm_time_threshold

        self.t_1 = threading.Thread(target=self.run, daemon=True)
        self._is_stopped = False

    def start(self):
        self.t_1.start()

    def stop(self):
        self._is_stopped = True

    def run(self):
        # print('Running')
        for kafka_message in self.input_stream:
            if self._is_stopped:
                break
            msg = kafka_message.value
            app_uuid = msg['uuid']
            app_name = msg['app_name']
            status_message = msg['status']
            time_stamp = msg['time_stamp']
            time_stamp_now = datetime.datetime.fromtimestamp(time_stamp, datetime.UTC)  # datetime.datetime.now()
            time_stamp_now_str = time_stamp_now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            
            messaging_app_is_new = app_uuid not in self.app_status
            if messaging_app_is_new:
                self.app_status[app_uuid] = {
                    'time_of_last_alarm': None,  # datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC),
                    'id_of_last_alarm': None,
                }  # time_stamp_now - self.alarm_time_threshold}
                # self.app_status[app_uuid]['time_of_last_alarm'] = time_stamp_now
            
            time_of_last_alarm = self.app_status[app_uuid]['time_of_last_alarm']
            ready_for_new_alarm = time_of_last_alarm is None or ((time_stamp_now - time_of_last_alarm).total_seconds() > self.alarm_time_threshold)

            if status_message == 'Emergency':
                # continue               
                
                alarm_already_issued = self.app_status[app_uuid]['id_of_last_alarm'] is not None and self.app_status[app_uuid]['status'] == 'Emergency'
                
                if alarm_already_issued:
                    # print('Alarm already issued')
                    self.app_status[app_uuid]['time_of_last_alarm'] = time_stamp_now
                
                elif ready_for_new_alarm:        
                    # print('Alarm issued!')
                    alarm_id = uuid.uuid4()
                    alarm_message = {
                        'uuid': alarm_id,
                        'time_stamp': time_stamp_now,
                        'app': app_uuid,
                        'app_name': app_name,
                        'type': 'init',
                        'message': 'Alarm issued',
                        # 'location': ...
                        # identifyers: {freq=0.5Hz} etc.
                    }
                    self.app_status[app_uuid]['time_of_last_alarm'] = time_stamp_now
                    self.app_status[app_uuid]['id_of_last_alarm'] = alarm_id
                    
                    # print(self.app_status[app_uuid].keys())
                    self.output_stream.send(self.alarm_topic, alarm_message)
                    self.output_stream.flush()

                else:   # Too soon for new alarm
                    pass
                    # print('To soon for new alarm')

            else:
                alarm_should_be_canceled = ready_for_new_alarm and self.app_status[app_uuid]['id_of_last_alarm'] is not None
                if alarm_should_be_canceled:
                    alarm_message = {
                        'uuid': self.app_status[app_uuid]['id_of_last_alarm'],
                        'time_stamp': time_stamp_now,
                        'app': app_uuid,
                        'app_name': app_name,
                        'type': 'not_critical',
                        'message': 'Alarm not critical anymore.',
                    }
                    self.app_status[app_uuid]['id_of_last_alarm'] = None
                    self.output_stream.send(self.alarm_topic, alarm_message)
                    self.output_stream.flush()

            
            # Record status of apps
            self.app_status[app_uuid].update({'name': app_name, 'status': status_message, 'time_stamp': time_stamp_now})
            # print(self.app_status)


# def run_app_monitoring(*config_args):
    # config = load_config(*config_args)
    # app_status_mon = AppStatusMonitoring(config)
    # app = QtWidgets.QApplication()

    # status_mon = AppStatusMonitoringWidget(config)
    # status_mon.start()
    # status_mon.show()
    # app.exec()


class AlarmMonitor:
    def __init__(
        self,
        io_kwargs,
        alarm_topic='alarms',
    ):
        
        self.input_stream = Consumer(
            alarm_topic, **io_kwargs
        )

        self.alarm_data = OrderedDict()
        self.alarm_events = {}
        self.t_1 = threading.Thread(target=self.run_alarm_consumer, daemon=True)

    def start(self):
        self.t_1.start()

    def run_alarm_consumer(self):
        for kafka_message in self.input_stream:
            alarm_event = kafka_message.value

            # 'uuid': uuid.uuid4(),
            # 'time_stamp': time_stamp_now,
            # 'app': app_uuid,
            # 'app_name': app_name,
            # 'type': 'init'
            # 'message: '...'
            # 'location': ...
            # 'identifiers': {freq=0.5Hz} etc.
            if alarm_event["uuid"] not in self.alarm_data:
                self.alarm_data[alarm_event['uuid']] = {
                    'app_name': alarm_event['app_name'],
                    'time_stamp': alarm_event['time_stamp'],
                    'time_stamp_end': None,
                    'status': 'unspecified',
                    'events': [],
                    }


            if alarm_event['type'] == 'init':
                self.alarm_data[alarm_event['uuid']]['status'] = 'unseen'
            elif alarm_event['type'] == 'not_critical':
                self.alarm_data[alarm_event['uuid']]['status'] = 'not_critical'
                self.alarm_data[alarm_event['uuid']]['time_stamp_end'] = alarm_event['time_stamp']
            elif alarm_event['type'] == 'acknowledge':
                self.alarm_data[alarm_event['uuid']]['status'] = 'acknowledged'
            elif alarm_event['type'] == 'silence':
                self.alarm_data[alarm_event['uuid']]['status'] = 'silenced'
            # elif alarm_event['type'] == 'delete':
                # self.alarm_data.pop(alarm_event['uuid'])

            # elif alarm_event['type'] == 'message':
                # self.alarm_data[alarm_event['uuid']]['messages'].append(alarm_event['message'])
            
            self.alarm_data[alarm_event['uuid']]['events'].append(alarm_event)

            # print(self.alarm_data)
        

    
if __name__ == '__main__':

    from pswamp import load_config
    config = load_config()
    config["streaming"]['consumers_seek_to_beginning'] = True
    # run_app_monitoring(config)
    alarm_sender = AlarmSender(
        io_kwargs=config["streaming"],
        input_topic=config['topics']['application.status'],
        alarm_topic=config['topics']['alarms'],
    )
    alarm_sender.start()
    # input('Press a key')

    alarm_monitor = AlarmMonitor(
        io_kwargs=config["streaming"],
        alarm_topic=config['topics']['alarms'],
    )
    alarm_monitor.start()
    input('Press a key')
