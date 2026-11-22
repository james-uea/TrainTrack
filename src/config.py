import os
from dataclasses import dataclass

from dotenv import dotenv_values

DEFAULT_TOPIC = "prod-1010-Darwin-Train-Information-Push-Port-IIII2_0-JSON"


@dataclass
class Config:
    database_url: str
    kafka_server: str | None
    kafka_username: str | None
    kafka_password: str | None
    kafka_group: str | None
    kafka_topic: str
    data_dir: str
    log_level: str
    map_clock: str


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
        data_dir=values.get("DATA_DIR") or "data",
        log_level=values.get("LOG_LEVEL") or "INFO",
        map_clock=values.get("MAP_CLOCK") or "now",
    )
