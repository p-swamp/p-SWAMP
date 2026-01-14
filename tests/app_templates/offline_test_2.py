from pswamp.utils.load_config import load_config
import pathlib
from pswamp.test_utils.csv_playback.offline_testing_adapter import OfflineTestingAdapter
from read_data import CustomInstructions


class OfflineTestingAdapterMod(CustomInstructions, OfflineTestingAdapter):
    pass


if __name__ == '__main__':
    config_file_path = pathlib.Path(r'examples/voltage_stability_case/config.toml')
    config = load_config(config_file_path)
    config["streaming"]['bootstrap_servers'] = 'localhost:51003'

    pmu_data_folder=pathlib.Path(pathlib.PureWindowsPath(r'examples\voltage_stability_case\data\pmu_data'))

    pmu_data_reader = OfflineTestingAdapterMod(
        pmu_data_folder=pmu_data_folder,
        case_name_hint='',
        # skip_rows=50*199 + 2
        # skip_until_time=199 - 1/50,
    )
    from pswamp.app_templates.snapshot_app import SnapshotApp
    app = SnapshotApp(io=pmu_data_reader, t_end=1)
    app.run()

    print('App finished')