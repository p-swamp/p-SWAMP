Examples
=================

Each of the examples are structured approximately as follows:


.. literalinclude:: examples_structure.txt

In short: the **readme.md** describes the example in detail, **config.toml** holds the configuration of the example, and the script **run_case.py** runs the example. The **apps** folder holds scripts to runn apps, and **data** holds various data files. These are described in detail in the following paragraphs.

Depending on the example, additional files might be present. These should be described in the readme of the example.

Running the examples
--------------------
The **run_case.py** script starts a number of processes (executed in parallel for improved performance), which do the following (among others):

* If NQKafka is used: A server is started, and the required topics (specified in **config.toml**) are created,
* PMU data is continuously sent to the PMU data topic of the Kafka server (depending on the example, the PMU data source can be a real-time simulation, which is also started by the script, or CSV-files with PMU data measurements),
* The main window of the GUI is shown.

Configuration
-------------

The configuration is specified in **config.toml**. This file specifies the following (among others):

* Whether to use Kafka or NQKafka for handling data streams,
* The IP and port to the Kafka (or NQKafka) server,
* The topics in the Kafka server,
* Paths to data files that are not accessed through Kafka.

Depending on the example, additional content might be specified.

Running apps
------------
Using the scripts in the **apps** folder, individual applications can be run (after **run_case.py** was run). Note that most (if not all) applications can be launched from the GUI. However, if some application is to be run with special input parameters, or if we want to debug a particular application, the scripts in the **apps** folder are useful. For efficient debugging, the **run_case.py** script can be run first, then a debug session can be started from one of the scripts in **apps**. In this way, the particular application can be started and stopped multiple times without having to restart the full example.

Data
----
The file **data/model_data.json** holds component parameters (e.g., nominal bus voltage levels, line capacities, etc.). The **data/sld.dxf** and **data/sld_geo.dxf** files are the single-line diagrams which are shown in the GUI. The dxf-format is a CAD format which can be edited using any compatible CAD program, for instance LibreCAD. In the dxf-files, the bus names are inserted (MText-entities), and lines are drawn between buses. Based on this and information in **data/model_data.json** (if supplied), the bus coordinates and branch path coordinates are automatically determined.

Note that the data files can be structured in other ways, as long as the paths in **config.toml** are updated accordingly.

The examples
------------
The examples in the repository are described below. There are other examples as well, but these are currently not described in detail. The links in the headers redirect to the readme files of each example.

.. :doc:`Recorded PMU data with oscillations <example_recorded_pmu_data>`
.. ______________________________________________________________________
.. This is an example with real historical PMU data capturing standing oscillations lasting for 1-2 minutes.

:doc:`Nordic 44 Real-Time Simulation<example_n44>`
______________________________________________________________________
In this example, a real-time simulation is run, producing PMU data which is streamed to the platform. Can be used for demonstrating oscillation monitoring, islanding detection or voltage stability monitoring.


.. :doc:`Multiple TSOs (builds on the Nordic 44 example)<example_n44_multi_tso>`
.. ______________________________________________________________________
.. This example is similar to the one above, but runs two separate instanceso of the platform. The intention of the example is to demonstrate coordination between TSOs.

.. :doc:`Generating streams from historical PMU data<example_csv_playback>`
.. ______________________________________________________________________

.. This example demonstrates playback of historical PMU data in an efficient way that is applicable to PMU data sets with hundreds of PMUs and thousands of channels.