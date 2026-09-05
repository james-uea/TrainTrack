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
    if data is None:
        return

    try:
        processed_data = json.loads(data)

        if not (raw_update_json := processed_data.get('bytes')):
            return

        json_data = json.loads(raw_update_json)

    except (JSONDecodeError, TypeError):
        return

    if 'uR' not in json_data:
        return

    status = extract_train_status(json_data)
    if status is not None:
        print(status, end='\n\n')

def extract_train_status(payload: dict) -> dict | None:
    update = payload.get("uR")
    if not isinstance(update, dict):
        return None

    status = update.get('TS')
    if not isinstance(status, dict):
        return None

    locations = status.get('Location', []) # Fetch Location, failing that return empty list
    if isinstance(locations, dict):
        locations = [locations]
    elif not isinstance(locations, list):
        locations = []

    return {
        "update_origin": update.get('updateOrigin'),
        "rid": status.get('rid'),
        "uid": status.get('uid'),
        "ssd": status.get('ssd'),
        "locations": locations
    }

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
                process(msg.value())
                # Store the offset associated with msg to a local cache.
                # Stored offsets are committed to Kafka by a background thread every 'auto.commit.interval.ms'.
                consumer.store_offsets(msg)

    except KeyboardInterrupt:
        sys.stderr.write('%% Aborted by user\n')

    finally:
        # Close down consumer to commit final offsets.
        consumer.close()

if __name__ == "__main__":
    main()
