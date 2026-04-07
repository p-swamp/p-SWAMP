# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

from pswamp.app_templates.time_window_app import TimeWindowApp
import numpy as np
from pswamp import load_config


class LineOutageDetectionApp(TimeWindowApp):

    def __init__(self, *args, eval_freq=1, threshold=0.01, n_samples=10, **kwargs):
        self.threshold = threshold
        TimeWindowApp.__init__(
            self,
            *args,
            eval_freq=eval_freq,
            n_samples=n_samples,
            report_status=True,
            **kwargs)
        self.col_idx = None
        # self.pca = PCA(6)
        self.line_outage_state = None

    def run_analysis(self, t, data):
        
        if np.any(np.isnan(t)):
            return

        # Should be in a separate initialization step before loop starts
        if self.col_idx is None:
            self.col_idx = self.tw.get_col_idx(measurement='i_Magnitude')
            self.line_outage_state = np.ones(len(self.col_idx), dtype=bool)

        current_data = data[:, self.col_idx]
        is_disconnected = np.all(current_data < self.threshold, axis=0)
        is_connected = ~is_disconnected
        # out_idx = np.where(disconnected)[0]
        # out_idx = np.array([140, 150, 145])
        # out_idx[140] = True
        # self.line_outage_state[140] = True
        incorrect_state = ~(self.line_outage_state == is_connected)
        
        disconnect_event = np.where(incorrect_state*is_disconnected)[0]
        connect_event = np.where(incorrect_state*is_connected)[0]
        if len(disconnect_event) == 0 and len(connect_event) == 0:
            return
        
        self.line_outage_state = is_connected
        
        events = []
        for event_name, event_channels in zip(['disconnect', 'connect'], [disconnect_event, connect_event]):
            if not any(event_channels):
                continue
            stations = [col[0] for col in self.tw.header[self.col_idx[event_channels]]]
            measurements = [col[1] for col in self.tw.header[self.col_idx[event_channels]]]
            print(stations, measurements, f'{event_name}ed')
            events.append({
                'type': event_name,
                'stations': stations,
                'measurements':  measurements,
            })

        return_value = {
            'time_stamp': t[-1],
            'info': {
                'app_name': self.app_name,
                'uuid': self.uuid,
            },
            'parameters': {
                'window_length': self.tw.n_samples*self.sampling_time,
            },
            'result': {
                'time_stamp': t[-1],
                'events': events
            },
        }
        self.set_status(return_value)
        return return_value

    def set_status(self, return_value):
        pass
        # Update status:
        # if len(return_value['result']['islands']) > 0:
            # self.status = 'Emergency'
        # elif ...:
            # self.status = 'Alert'
        # else:
            # self.status = 'OK'
    


def run_line_outage_application(config):

    # Define the application
    app = LineOutageDetectionApp(
        # window_length=10,
        input_topic=config['topics']['pmudata'],
        output_topic=config['topics']['grid.events'],
        status_topic=config['topics']['application.status'],
        io_kwargs=config["streaming"],
        eval_freq=10,
    )

    # Run the application
    app.run()


if __name__ == '__main__':
    config = load_config()
    config["streaming"]['bootstrap_servers'] = 'localhost:40000'
    config["streaming"]['consumers_seek_to_beginning'] = True
    run_line_outage_application(config)
