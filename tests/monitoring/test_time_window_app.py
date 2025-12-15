from pswamp.test_utils.sample_datasets.mock_case import run_mock_case, stop_mock_case
from pswamp.app_templates.time_window_app import TimeWindowApp
from pswamp import load_config


class MyApp(TimeWindowApp):
    def run_analysis(self, t, data):
        print(t[-1])


if __name__ == "__main__":

    config = load_config()
    config['kafka']['bootstrap_servers'] = 'localhost:51004'
    config['kafka']['consumers_seek_to_beginning'] = True
        
    mock_case = run_mock_case(config)
    
    print('Defining app')
    tw_app = MyApp(
        kafka_kwargs=config['kafka'],
        input_topic='pmudata',
        n_samples=10,
        t_end=10,
    )

    print('Starting app')
    tw_app.run()
    print('App finished')
    stop_mock_case(config)
