from pswamp.streaming.base import Consumer, Producer
import threading
import sys
import time



def run_consumer(streaming_kwargs, n_msgs):
    kafka_consumer = Consumer('time', **streaming_kwargs)

    k = 0
    msg_gen = iter(kafka_consumer)
    while k < n_msgs:
        msg = next(msg_gen)
        t_send, k_prod, payload = msg.value
        if not k == k_prod:
            print('Wrong message received!')
        else:
            sys.stdout.write('\rCorrect message received (#{}). Delay: {:.1f} ms.'.format(k, 1e3*(time.time() - t_send)))
        k += 1

    print('\nCONSUMER: All messages received')


def run_producer(streaming_kwargs, n_msgs):
    kafka_producer = Producer(**streaming_kwargs)  # 'localhost:9092')

    k = 0
    while k < n_msgs:
        time.sleep(0.1)

        payload = [1, 2, 3]
        kafka_producer.send('time', [time.time(), k, payload])
        kafka_producer.flush()
        k += 1

    print('\nPRODUCER: All messages sent')


def test():
    config = {
        "streaming": {
            "type": "mqtt",
            "hostname": "localhost",
            "port": 1883
        }
    }

    n_msgs = 10

    p_consumer = threading.Thread(target=run_consumer, args=(config["streaming"], n_msgs,))
    p_consumer.start()

    p_producer = threading.Thread(target=run_producer, args=(config["streaming"], n_msgs,))
    p_producer.start()

    p_consumer.join()
    p_producer.join()

    sys.exit()


if __name__ == '__main__':
    test()