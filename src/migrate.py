import os

from db import Database


def main():
    db = Database()

    db.cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

    db.cur.execute('SELECT version FROM schema_migrations;')
    versions = [row[0] for row in db.cur.fetchall()]
    migrations = sorted(os.listdir('sql/migrations'))
    migrations = [migration for migration in migrations if migration not in versions]

    print(f"{len(versions)} Migration(s) already applied. {len(migrations)} pending")

    for migration in migrations:
        print(f"Applying migration: {migration}")

        with open(f'sql/migrations/{migration}', 'r') as f:
            migration_sql = f.read()
            db.cur.execute(migration_sql)

        db.cur.execute("INSERT INTO schema_migrations (version) VALUES (%s);", (migration,))
        print("Migration applied")

    db.commit()
    db.close()

if __name__ == "__main__":
    main()
