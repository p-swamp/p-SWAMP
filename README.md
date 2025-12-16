# p-SWAMP (Power Stability Wide area Monitoring and Protection)

The code in this repository is based on previous code from the NEWEPS research project.

## Installation
This Python package can be installed as follows:

1. Clone the repository using Git (or download and unzip manually),
2. Create a virtual environment and activate it,
3. Install the p-SWAMP-package using pip:
    
    ```typescript
    pip install -e .[full]
    ```
    The "-e" allows code to be edited without requiring reinstalling. "[full]" causes extra dependencies to be installed, which are required to run the examples.


## Quick start
Two examples can be run once the package is installed (found in the "examples" folder). Follow the readme in the subfolders for instructions on how to run the examples.

The examples can be run in two different modes:

* <strong> With Kafka</strong>: This requires a running Kafka server, as discussed further below.

* <strong>With NQKafka</strong>, which is a lightweight replacement of Kafka. With NQKafka, a server can be started easily from within Python without requiring installing extra software.

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
