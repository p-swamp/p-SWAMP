Streaming, microservices, Kafka
=====

The Kafka stream processing framework is used to handle data streams between microservices. Using Kafka requires a dedicated Kafka server. A Kafka server is a Java application which can be run on different operating systems, but the most stable and common options are to run the server either on a Linux machine, or renting a Kafka server as a service from a dedicated provider (Software-as-a-Service, Saas).

..
    For development and testing, any of the above options can be used. For deployments expected to run for longer durations of time, one of the more stable options should be used, e.g. running a Kafka server on a dedicated Linux server, or using a SaaS provider to run Kafka in the cloud.

Lightweight Kafka alternative
-------------------------
In the development and testing phase, it is useful to be able to run short-lived instances of the platform, e.g., to run a unit test, or run a demonstration of a new concept. To avoid the dependence of a full-blown Kafka server in such situations, a lightweight and simplistic alternative to Kafka was developed within the project (i.e., a "mock" in data science terms). This Python package, NQKafka, is `available on GitHub <https://github.com/hallvar-h/nqkafka>`_, and implements the most basic and fundamental functionality of Kafka, i.e. creation of topics, producers and consumers, using only standard Python packages. The performance of this alternative is by no means comparable to a proper Kafka server, but allows testing simple setups for short durations of time (e.g. minutes to tens of minutes), either running on a single computer or in a distributed setup.

This alternative is useful in the early stages of development and testing of new WAMPAC applications and for automatic unit testing of code.

Kafka server
-------------------------
Some alternatives for setting up a proper Kafka server are outlined in the following.

* **Windows**: Kafka can run on Windows, but is not developed for this operating system and is thus not expected to be stable over time.
* **Linux**: This is a better option than the previous, considering ease of deployment and configuration, and performance. The obvious disadvantage is that this requires a dedicated computer with Linux installed.
* **Windows Subsystem for Linux (WSL)**: Running a Linux environment within Windows, where a Kafka server can be run. Our experience is that this works satisfactory for setups running on a single computer. However, achieving a distributed setup, where different computers connect to the Kafka server running in WSL, is not as straightforward.
* **NQKafka**: As mentioned above, a "mock" of the Kafka server allows the platform to be tested without a proper Kafka server.
* **Software as a Service (SaaS)**: A Kafka server can be run in the cloud. There are several providers of such services, which relieve the user from having to install, configuring and run a Kafka server. The downside is that such services are not free, and are charged based on the number of topics, data storage, number of consumers or producers, etc.

In summary: For development and testing, any of the above options can be used. For deployments expected to run for longer durations of time, one of the more stable options should be used, e.g. running a Kafka server on a dedicated Linux server, or using a SaaS provider to run Kafka in the cloud.