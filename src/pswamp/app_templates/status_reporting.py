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

import datetime
import uuid


class ReportingApp:
    """Implements the reporting functionality of applications. Uses a timer to
    determine when to emit status messages.

    TODO: Rename so it does not look like an application template.
    
    Args:
        parent: The application for which the reporting is done.
        status_update_freq: How often the reporting is done (default is once
            per second).
    """
    def __init__(self, parent, status_update_freq=1):
        self.parent = parent
        self.io = self.parent.io
        self.status_update_freq = status_update_freq

        self.status_update_timer = None
        self.t_next_status = None
        self.t_status_target = round(1/self.status_update_freq, 2)

    def communicate_status(self):
        """Determine when to send a new status message, generate the message,
        and hand it over to the io object of the parent.
        """
        current_time = self.parent.most_recent_time_stamp

        if self.t_next_status is None:
            self.t_next_status = current_time

        if current_time >= self.t_next_status:
            message = {
                'uuid': self.parent.uuid,
                'app_name': self.parent.app_name,
                'status': self.parent.status,
                'time_stamp': current_time,
            }
            self.io.handle_status(message)
            self.t_next_status += self.t_status_target


class AlarmHandler:
    def __init__(self, app, alarms_topic="alarms", alarm_time_threshold=15):
        self.app = app
        self.alarms_topic = alarms_topic

        self.time_of_last_alarm = None
        self.id_of_last_alarm = None
        self.alarm_time_threshold = alarm_time_threshold

    def update(self):
        
        time_stamp = self.app.most_recent_time_stamp
        time_stamp_dt = datetime.datetime.fromtimestamp(time_stamp, datetime.UTC)
        ready_for_new_alarm = self.time_of_last_alarm is None or (
             (time_stamp_dt - self.time_of_last_alarm).total_seconds() >\
                self.alarm_time_threshold)

        if not ready_for_new_alarm:
            return
        
        if self.app.status == "Emergency":
            self.time_of_last_alarm = time_stamp_dt
            alarm_already_active = self.id_of_last_alarm is not None
            if alarm_already_active:
                return
            
            self.id_of_last_alarm = uuid.uuid4()
            alarm_message = {
                'uuid': self.id_of_last_alarm,
                'time_stamp': time_stamp_dt,
                'app': self.app.uuid,
                'app_name': self.app.app_name,
                'type': 'init',
                'message': 'Alarm issued',
                # 'location': ...
                # 'identifiers': {freq=0.5Hz} etc.
            }                
        
        elif self.id_of_last_alarm is not None:
            alarm_message = {
                'uuid': self.id_of_last_alarm,
                'time_stamp': time_stamp_dt,
                'app': self.app.uuid,
                'app_name': self.app.app_name,
                'type': 'not_critical',
                'message': 'Alarm not critical anymore.',
            }
            self.id_of_last_alarm = None
        
        else:
            return

        self.app.status
        self.app.io.handle_output(self.alarms_topic, alarm_message)
