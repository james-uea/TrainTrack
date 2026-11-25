"""
Consume Network Rail's Train Describer from Kafka and store every berth step, cancel and interpose in `td_steps`.

    uv run src/td_consumer.py
"""

import logging
import socket
import time
from collections import Counter
from datetime import datetime

from confluent_kafka import Consumer, KafkaException

import retention
from config import load_config
from db import Database
from td import parse_td
from util import LONDON

logger = logging.getLogger("td_consumer")

STATS_INTERVAL_SECONDS = 60
# Steps are written in batches: at least this often, or sooner once this many have arrived
BATCH_SECONDS = 1.0
BATCH_STEPS = 2000


def build_consumer(config) -> Consumer:
    settings = ("td_kafka_server", "td_kafka_username", "td_kafka_password", "td_kafka_group")
    missing = [name for name in settings if not getattr(config, name)]
    if missing:
        raise RuntimeError(f"Missing Train Describer settings: {', '.join(name.upper() for name in missing)}")

    return Consumer({
        'bootstrap.servers': config.td_kafka_server,
        'group.id': config.td_kafka_group,
        'session.timeout.ms': 6000,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanism': 'PLAIN',
        'sasl.username': config.td_kafka_username,
        'sasl.password': config.td_kafka_password,
        'enable.auto.offset.store': False,
        'client.id': socket.gethostname(),
    }, logger=logging.getLogger("kafka"))


def main():
    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    logger.info("Connecting to %s, topic %s", config.td_kafka_server, config.td_kafka_topic)
    consumer = build_consumer(config)
    consumer.subscribe([config.td_kafka_topic], on_assign=lambda _, partitions: logger.info("Assigned %s", partitions))
    db = Database(config.database_url)
    retention.ensure_partitions(db, datetime.now(LONDON).date(), ahead=1)

    counts: Counter = Counter()
    batch, last_message = [], None
    last_write = last_stats = time.monotonic()
    try:
        while True:
            msg = consumer.poll(timeout=0.5)
            if msg is not None:
                if msg.error():
                    raise KafkaException(msg.error())
                counts["messages"] += 1
                batch.extend(parse_td(msg.value() or b"", counts))
                last_message = msg

            now = time.monotonic()
            if last_message is not None and (len(batch) >= BATCH_STEPS or now - last_write >= BATCH_SECONDS):
                if batch:
                    db.in_transaction(lambda steps=batch: db.add_td_steps(steps), "storing berth steps")
                    counts["stored"] += len(batch)
                # Offsets are stored only once their steps are committed, and sent to Kafka in the background
                consumer.store_offsets(last_message)
                batch, last_message, last_write = [], None, now

            if now - last_stats >= STATS_INTERVAL_SECONDS:
                logger.info("Last %ss: %s", STATS_INTERVAL_SECONDS, ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
                counts.clear()
                last_stats = now

    except KeyboardInterrupt:
        logger.info("Aborted by user")

    finally:
        consumer.close()
        db.close()


if __name__ == "__main__":
    main()
