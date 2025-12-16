# Define the line model:
line_model = Line(
    config,
    pmu_data_config,
    units=['L3000-L3245-1', 'L3000-L3245-2'])

# Quantities can now be calculated from PMU data frames
line_model.P_from(pmu_data_frame)
line_model.Q_from(pmu_data_frame)