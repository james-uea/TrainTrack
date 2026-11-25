import os
from dataclasses import dataclass

from dotenv import dotenv_values

DEFAULT_TOPIC = "prod-1010-Darwin-Train-Information-Push-Port-IIII2_0-JSON"
# The Rail Data Marketplace gives no topic name for Train Describer; this is the one its account can read
DEFAULT_TD_TOPIC = "TD_ALL_SIG_AREA"


@dataclass
class Config:
    database_url: str
    kafka_server: str | None
    kafka_username: str | None
    kafka_password: str | None
    kafka_group: str | None
    kafka_topic: str
    td_kafka_server: str | None
    td_kafka_username: str | None
    td_kafka_password: str | None
    td_kafka_group: str | None
    td_kafka_topic: str
    data_dir: str
    log_level: str
    map_clock: str
    events_keep_days: int  # days of raw events kept in Postgres before they're archived
    frames_keep_days: int  # days of recorded map frames kept; 0 keeps them forever
    td_keep_days: int  # days of Train Describer berth steps kept; 0 keeps them forever
    archive_dir: str


def load_config(path: str = ".env") -> Config:
    """Read settings from `.env`, letting real environment variables (e.g. from Docker Compose) win."""
    values = {**dotenv_values(path), **os.environ}

    database_url = values.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")

    return Config(
        database_url=database_url,
        kafka_server=values.get("KAFKA_SERVER"),
        kafka_username=values.get("KAFKA_USERNAME"),
        kafka_password=values.get("KAFKA_PASSWORD"),
        kafka_group=values.get("KAFKA_GROUP"),
        kafka_topic=values.get("KAFKA_TOPIC") or DEFAULT_TOPIC,
        td_kafka_server=values.get("TD_KAFKA_SERVER"),
        td_kafka_username=values.get("TD_KAFKA_USERNAME"),
        td_kafka_password=values.get("TD_KAFKA_PASSWORD"),
        td_kafka_group=values.get("TD_KAFKA_GROUP"),
        td_kafka_topic=values.get("TD_KAFKA_TOPIC") or DEFAULT_TD_TOPIC,
        data_dir=values.get("DATA_DIR") or "data",
        log_level=values.get("LOG_LEVEL") or "INFO",
        map_clock=values.get("MAP_CLOCK") or "now",
        events_keep_days=int(values.get("EVENTS_KEEP_DAYS") or 14),
        frames_keep_days=int(values.get("FRAMES_KEEP_DAYS") or 0),
        td_keep_days=int(values.get("TD_KEEP_DAYS") or 14),
        archive_dir=values.get("ARCHIVE_DIR") or os.path.join(values.get("DATA_DIR") or "data", "archive"),
    )
