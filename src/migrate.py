import logging
import os

from config import load_config
from db import Database

logger = logging.getLogger("migrate")

MIGRATION_LOCK = 1010

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql", "migrations")


def apply_migrations(db: Database, migrations_dir: str = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in one transaction. Returns the ones applied."""
    # Two services start by migrating; the second waits here for the first, then finds nothing pending
    db.cur.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
    db.cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

    db.cur.execute('SELECT version FROM schema_migrations;')
    versions = [row[0] for row in db.cur.fetchall()]
    migrations = sorted(name for name in os.listdir(migrations_dir) if name.endswith(".sql"))
    pending = [migration for migration in migrations if migration not in versions]

    logger.info("%d migration(s) already applied, %d pending", len(versions), len(pending))

    for migration in pending:
        logger.info("Applying migration: %s", migration)
        with open(os.path.join(migrations_dir, migration)) as f:
            db.cur.execute(f.read())
        db.cur.execute("INSERT INTO schema_migrations (version) VALUES (%s);", (migration,))

    db.commit()
    return pending


def main():
    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(config.database_url)
    try:
        apply_migrations(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
