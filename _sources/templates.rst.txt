Real-Time Application Templates
==============

Two main application templates are available:

* SnapshotApp
* TimeWindowApp

The second template inherits from the first, where the main difference is that the TimeWindowApp stores data in an array.

New applications can be implemented by inheriting from the templates. In principle, the only functions that should be defined by a new application is the "run_analysis" method and, if neccessary, initialization. Additionally, parameters are specified, determining, among others:

* How often to run the analysis (which could be less often than new data frames are received),
* Whether or not the application sends status messages to the application-status-topic (this is valuable for monitoring applications, but not neccessary for visualization applications),
* How the input data frames are read; by default, the input is assummed to be PMU data frames according to the C37.118 standard, but other methods for reading the input could be specified,
* TimeWindowApp only: The length of the time window storage (in seconds or samples). If no length is specified, the window length will increase indefinitely as new samples are obtained.