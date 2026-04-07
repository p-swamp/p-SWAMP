# p-SWAMP (Power Stability Wide area Monitoring and Protection)
This repo contains a Python package for enabling development and testing of WAMPAC applications. The code is based on developments in the research project [NEWEPS](https://ri.diva-portal.org/smash/record.jsf?pid=diva2%3A1933825&dswid=2773), and is described in this paper:

[*H. Haugdal, S. D’Arco and K. Uhlen, "A Platform for Development and Testing of WAMPAC Applications based on Kafka Streaming," 2024 IEEE PES Innovative Smart Grid Technologies Europe (ISGT EUROPE), Dubrovnik, Croatia, 2024.*](https://ieeexplore.ieee.org/document/10863035)

In the NEWEPS project, several demonstration videos were created, which can be accessed below. Note, however, that not all the functionality shown in the videos is available here.
[![Videos](https://img.youtube.com/vi/IB7JYJ0BG9U/0.jpg)](https://www.youtube.com/playlist?list=PLE8zTKw5VFOGFu1mKQllDV4mm9gt1W3zd)

**NOTE:** This code is being developed as part of ongoing research, and thus contains experimental features. Use at your own risk!


## Installation
This Python package can be installed using pip (or another package manager, for instance uv):    
```typescript
pip install -e .[full]
```
"[full]" causes extra dependencies to be installed, which are required to run the examples.


## Quick start
Two examples can be run once the package is installed (found in the "examples" folder). Follow the readme in the subfolders for instructions on how to run the examples.

The examples can be run using different streaming platforms:

* <strong>Kafka</strong>: This requires a running Kafka server, as discussed further below.

* <strong>NQKafka</strong>: This is a lightweight replacement of Kafka. With NQKafka, a server can be started from within Python.

* <strong> MQTT</strong>: Supporting MQTT is work in progress.

By default, the examples are configured to use the second option (NQKafka).

## Status
Currently, a few sample monitoring applications/microservices are included in the repository, among others:
* **N4SID Mode Estimation:** Monitoring of electromechanical oscillations, producing estimates of oscillation frequency, damping and observability mode shapes.
* **Mode Estimation Visualization:** Visualization of results from Mode Estimation applications.
* **FFT Visualization:** Visualization of FFT (Fast Fourier Transform) of signals.
* **Islanding detection:** Monitoring application to detect islanding operation.

Additionally, some plotting functions and basic GUI functions are implemented (e.g. for launching applications).

## Kafka
Kafka is chosen as the framework for facilitating communication between different monitoring applications. This requires installing and running a Kafka server. Once the server is running, applications can connect to the server. Within the Kafka framework, communication between applications is achieved through *Topics*. A *Producer* puts a *message*/*event*/*record* into a specific topic, and messages can be consumed by *Consumers* subscribing to specific topics. To use Kafka with Python, the package [kafka-python](https://kafka-python.readthedocs.io/en/master/) is used, where the consumer and producer functionality is available in the *KafkaConsumer* and *KafkaProducer* classes.

A Kafka server can be installed and run on different platforms. Currently, the following options have been tested:
* **Linux:** This is the recommended option.
* **Windows:** A server can be run in Windows, but this might have issues as Kafka is not developed for Windows. (For example, deleting topics or deleting parts of the log might cause errors.)
* **Windows Subsystem for Linux (WSL)**: This also works.

In short, setting up a server requires installing Java, downloading and extracting some files and running some scripts. There are many guides available online for doing this, both for Linux, Windows and WSL.

For running small demonstrations (i.e. a few diffrent applications, lasting minutes-tens of minutes), the high performance of Kafka is not strictly neccessary. Therefore, a much simpler lightweight alternative to Kafka has been implemented, NQKafka (Not-Quite-Kafka), which allows running small setups without requiring installing and configuring a Kafka server.

The possibility of running the platform with MQTT instead of Kafka is being investigated.
