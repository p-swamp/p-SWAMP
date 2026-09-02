# Example: Real-time Simulation of the Nordic 44 Bus System
*Located in the repository in **examples/nordi44_rtsim***

In this example, a real-time simulation of the Nordic 44 Bus System is performed using the packages TOPS and TOPS-RT. The voltages at all buses, as well as electric frequency and line and transformer currents, are streamed during the simulation in the C37.118 format using the PyPMU package. The PMU stream is forwarded to Kafka, and analyzed/visualized with any of the selected applications.

By default, the example uses NQKafka instead of real Kafka. NQKafka (Not-Quite-Kafka) was written to allow the code to run without requiring setting up a Kafka server.  To use real Kafka instead, the field use_nqkafka_server can be set to False in the config.py file (this requires a running Kafka server).

## To run the example
1. Run the script **run_case.py**. This will automatically start/run a number of things:
   * Starting a NQKafka server,
   * Creating the required topics,
   * Starting a real-time simulation of the Nordic 44 bus system, which sends C37.118 data frames to the NQKafka server,
   * Starting the main window.
2. Launch an application by clicking one or more of the buttons that appear, or by running one of the "apps" in the folder
   * **main_window.py**: Run main window
   * **fft_viz.py**: FFT visualization
   * **time_window_plot.py**: Time window plot of the PMU stream
   * **some_rt_app.py**: Example real time application (template/empty box)


## To run the example through a PDC
The example can also be run through a PDC, where the real-time simulation
streams data to the PDC (according to C37.118), and the PDC streams data to the 
P-SWAMP platform. To do this, IPs and ports must be configured properly in
**config.toml**: under `[pmus]` for the real-time simulation, and under `[pdc]` for
the PDC.

To start the real-time simulation, the script **run_sim.py** is run.
(Other C37.118 compatible tools can also connect to this stream, e.g.,
[PMU Connection Tester](https://github.com/GridProtectionAlliance/PMUConnectionTester).)

To run the P-SWAMP demo platform, run the script **run_gui.py**. If the IP and
ports for `[pmus]` and `[pdc]` are the same in **config.toml**, the platform will
connect directly to the real-time simulation stream. If there is a PDC inbetween, the IPs
and ports must be changed accordingly.
