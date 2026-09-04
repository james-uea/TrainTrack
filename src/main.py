import json
import logging
import socket
import sys
from json import JSONDecodeError

from confluent_kafka import Consumer, KafkaException
from dotenv import dotenv_values

config = dotenv_values(".env")

print(f"Authenticating with {config['KAFKA_USERNAME']}@{config['KAFKA_SERVER']}")

topics = ['prod-1010-Darwin-Train-Information-Push-Port-IIII2_0-JSON']

conf = {'bootstrap.servers': config['KAFKA_SERVER'],
        'group.id': config['KAFKA_GROUP'],
        'session.timeout.ms': 6000,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanism': 'PLAIN',
        'sasl.username': config['KAFKA_USERNAME'],
        'sasl.password': config['KAFKA_PASSWORD'],
        "enable.auto.offset.store": False,
        'client.id': socket.gethostname()}

logger = logging.getLogger('consumer')
logger.setLevel(logging.DEBUG)

def print_assignment(consumer, partitions):
    print('Assignment:', partitions)

def process(data):
    try:
        processed_data = json.loads(data)
    except JSONDecodeError:
        return

    if processed_data.get('messageType') != "bytes" or not processed_data.get('bytes'):
        return

    byte_data = processed_data['bytes']
    json_data = json.loads(byte_data)

    if 'uR' not in json_data:
        return

    uR = json_data['uR']
    print(uR.keys())

def main():
    consumer = Consumer(conf, logger=logger)
    consumer.subscribe(topics, on_assign=print_assignment)

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                raise KafkaException(msg.error())
            else:
                # Proper message
                sys.stderr.write(
                    f'%% {msg.topic()} [{msg.partition()}] at offset {msg.offset()} with key {msg.key()!s}:\n'
                )
                process(msg.value())
                # Store the offset associated with msg to a local cache.
                # Stored offsets are committed to Kafka by a background thread every 'auto.commit.interval.ms'.
                # Explicitly storing offsets after processing gives at-least once semantics.
                consumer.store_offsets(msg)

    except KeyboardInterrupt:
        sys.stderr.write('%% Aborted by user\n')

    finally:
        # Close down consumer to commit final offsets.
        consumer.close()

if __name__ == "__main__":
    main()
