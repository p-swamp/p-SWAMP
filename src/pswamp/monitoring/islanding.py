from pswamp.app_templates.time_window_app import TimeWindowApp
from pswamp.app_templates.status_reporting import AlarmHandler
import numpy as np
from pswamp import load_config


def moving_average(x, w):
    return np.convolve(x, np.ones(w), 'valid') / w


def detect_islands(t, data, mean_threshold=0.05):
    if np.any(np.isnan(t)):
            return           

    freq_raw = data  # [:, self.col_idx]

    freq = np.array([moving_average(f, 10) for f in freq_raw.T]).T
    mean_freq = np.mean(freq, axis=0)

    i_island = 0
    n_islands_max = 10

    island_idx = -np.ones(freq.shape[1], dtype=int)
    assigned = np.zeros(freq.shape[1], dtype=bool)
    assigned[np.isnan(mean_freq)] = True

    islands = []

    while i_island < n_islands_max:

        ref_meas = np.argmax(~assigned)

        same_mv_avg_as_ref_meas = np.linalg.norm(
            freq[:, [ref_meas]] - freq, axis=0)/np.sqrt(len(t)) < mean_threshold
        
        assign_these = same_mv_avg_as_ref_meas
        island_idx[assign_these & ~assigned] = i_island
        assigned += assign_these

        islands.append(np.where(assign_these)[0])
        
        if np.all(assigned):
            break

        i_island += 1

    sort_idx = np.argsort([-len(island_) for island_ in islands])
    islands = [islands[idx_] for idx_ in sort_idx]
    islands = islands[1:]
    
    return t[-1], islands


class IslandingApp(TimeWindowApp):
    def __init__(self, *args, eval_freq=1, window_length=10, **kwargs):

        TimeWindowApp.__init__(
            self,
            *args,
            window_length=window_length,
            eval_freq=eval_freq,
            decoder_kwargs={
                'substitute_zero_freq_with_nan': True,
                'channel_selection': {'measurement': 'f'}},
            report_status=True,
            **kwargs)
        
        self.init(*args)
        self.alarm_handler = AlarmHandler(self)
        self.update_callbacks.append(self.alarm_handler.update)
        
    def init(self, mean_threshold=0.05):
        self.mean_threshold = mean_threshold
        self.col_idx = self.tw.get_col_idx()
        # self.pca = PCA(6)

    def run_analysis(self, t, data):
        
        res = detect_islands(t, data)
        if res is None:
            return
        
        t_assess, islands = res

        return_value = {
            'time_stamp': t[-1],
            'info': {
                'app_name': self.app_name,
                'uuid': self.uuid,
            },
            'parameters': {
                'window_length': self.tw.n_samples*self.sampling_time,
                'mean_threshold': self.mean_threshold,
                'eval_freq': self.eval_freq,
            },
            'result': {
                'time_stamp': t_assess,
                'islands': islands,
            },
        }
        self.set_status(return_value)
        return return_value

    def set_status(self, return_value):
        # Update status:
        if len(return_value['result']['islands']) > 0:
            self.status = 'Emergency'
        # elif ...:
            # self.status = 'Alert'
        else:
            self.status = 'OK'
    


def run_islanding_application(config, **kwargs):

    # Define the application
    app = IslandingApp(
        # window_length=10,
        input_topic=config['topics']['pmudata'],
        output_topic=config['topics']['islanding'],
        status_topic=config['topics']['application.status'],
        kafka_kwargs=config['kafka'],
        # eval_freq=1,
        **kwargs
    )

    # Run the application
    app.start()


if __name__ == '__main__':
    config = load_config()
    config['kafka']['bootstrap_servers'] = 'localhost:40000'
    run_islanding_application(config)
