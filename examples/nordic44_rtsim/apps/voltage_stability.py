from pswamp.monitoring.voltage_stability import VoltageStabilityApp
from pswamp.utils.load_config import load_config
from pswamp.monitoring.voltage_stability_indicators.corsi_taranto import VSI
# from pswamp.monitoring.voltage_stability_indicators.new_vsi_v2 import VSI


if __name__ == '__main__':

    
    config = load_config('..')
    vs_mon = VoltageStabilityApp(
        kafka_kwargs=config['kafka'],
        input_topic=config['topics']['pmudata'],
        output_topic=config['topics']['voltage.stability.index'],
        status_topic='application.status',
        station='5610',
        voltage_measurement='V',
        current_measurement='I[L5603-5610]',
        load_current_direction=-1,
        eval_freq=None,
        vsi_type=VSI,
    )
    vs_mon.run()