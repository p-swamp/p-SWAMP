

sample_pdc_data = {
    "pdc_id": "RTAC_CIRCE",
    "timestamp": "2025-09-10T10:28:06.4800000Z",
    "pmu": [
        {
            "device_id": "BUSBAR1_A",
            "location": "substation-A",
            "timestamp": "2025-09-10T10:28:06.4800000Z",
            "phasors": [
                {
                    "value_id": "V_phase_A",
                    "frequency": 49.98,
                    "magnitude": 10000.57,
                    "phase": -1.57,
                    "unit": "kV",
                    "rocof": -0.053,
                    "reference_frame": "line",
                },
                {
                    "value_id": "I_phase_A",
                    "frequency": 49.98,
                    "magnitude": 10000.57,
                    "phase": -1.57,
                    "unit": "kA",
                    "rocof": -0.053,
                    "reference_frame": "line",
                }
            ],
        }
    ],
}



if data["type"] == "c37118":
    current_phasor_extractor_from = PMUPhasorExtractor(
        wanted_stations=bus_data['name'][self.from_bus_idx].to_list(),
        wanted_channels=[[f'I[{unit}]'] for unit in units], **phasor_extractor_kwargs
    )
elif data["type"] == "json_interscada":

    bus_voltage_extractor = Extractor(
        wanted_stations=bus_data["location"]
        value_ids="V_phase_A"
    )
    current_phasor_extractor_from = Extractor(
        
    )

