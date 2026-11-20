"""
Consume the Darwin Push Port from Kafka, log every message and apply it to the database.

    uv run src/consumer.py                      # normal running
    uv run src/consumer.py --record out.jsonl   # also save raw messages, e.g. to build test fixtures
"""

import argparse
import logging
import socket
import time

from confluent_kafka import Consumer, KafkaException

from config import load_config
from darwin import parse_message
from db import Database

logger = logging.getLogger("consumer")

STATS_INTERVAL_SECONDS = 60


def build_consumer(config) -> Consumer:
    missing = [name for name in ("kafka_server", "kafka_username", "kafka_password", "kafka_group") if not getattr(config, name)]
    if missing:
        raise RuntimeError(f"Missing Kafka settings: {', '.join(name.upper() for name in missing)}")

    return Consumer({
        'bootstrap.servers': config.kafka_server,
        'group.id': config.kafka_group,
        'session.timeout.ms': 6000,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanism': 'PLAIN',
        'sasl.username': config.kafka_username,
        'sasl.password': config.kafka_password,
        'enable.auto.offset.store': False,
        'client.id': socket.gethostname(),
    }, logger=logging.getLogger("kafka"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--record", metavar="FILE", help="append every raw Kafka message to FILE (one per line)")
    args = parser.parse_args()

    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    logger.info("Authenticating with %s@%s, topic %s", config.kafka_username, config.kafka_server, config.kafka_topic)
    consumer = build_consumer(config)
    consumer.subscribe([config.kafka_topic], on_assign=lambda _, partitions: logger.info("Assigned %s", partitions))
    db = Database(config.database_url)
    record = open(args.record, "ab") if args.record else None  # noqa: SIM115 (closed in finally)

    totals: dict[str, int] = {"messages": 0, "unparsed": 0}
    last_stats = time.monotonic()

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is not None:
                if msg.error():
                    raise KafkaException(msg.error())

                data = msg.value()
                if data:
                    totals["messages"] += 1
                    if record:
                        record.write(data.rstrip(b"\n") + b"\n")

                    message = parse_message(data)
                    if message is None:
                        totals["unparsed"] += 1
                    else:
                        for key, value in db.handle_message(message).items():
                            totals[key] = totals.get(key, 0) + value

                # Stored offsets are committed to Kafka by a background thread every 'auto.commit.interval.ms'.
                consumer.store_offsets(msg)

            if time.monotonic() - last_stats >= STATS_INTERVAL_SECONDS:
                logger.info("Last %ss: %s", STATS_INTERVAL_SECONDS, ", ".join(f"{k}={v}" for k, v in totals.items()))
                totals = dict.fromkeys(totals, 0)
                last_stats = time.monotonic()

    except KeyboardInterrupt:
        logger.info("Aborted by user")

    finally:
        # Close down consumer to commit final offsets.
        consumer.close()
        db.close()
        if record:
            record.close()


if __name__ == "__main__":
    main()
