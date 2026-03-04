Component models
================

PMUs measure voltages and currents (among othes). By giving systematic names to the measurement channels, it is possible to determine what actual components/elements the currents flow through, and what are the voltages at the terminals of the components/elements. This further allows us to do calculations, e.g., by using the current and voltage to determine the power flow in a line.

This is what the implemented "component models" do. Currently, models for the following components are available:

* Buses
* Lines
* Loads

The models are used as follows:

.. literalinclude:: models_example.py

In a real-time application, it makes sense to define the model (first 5 lines in the example) when the application is initialized. This is where searching for channel names, etc., happens. Then, as the application is running in real-time, it runs the calculations efficiently (as in the last two lines).
