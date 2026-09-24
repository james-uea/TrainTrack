import psycopg
from psycopg import sql


class Database:

    def __init__(self):
        from dotenv import dotenv_values
        config = dotenv_values(".env")
        self.database_url = config['DATABASE_URL']

        self.conn, self.cur = self.connect(self.database_url)

    def connect(self, database_url):
        conn = psycopg.connect(database_url)
        cur = conn.cursor()
        return conn, cur

    def add_code_maps(self, table, key_col, value_col, code_map):
        query = sql.SQL("""
            INSERT INTO {table} ({key_col}, {value_col})
            VALUES (%s, %s)
            ON CONFLICT ({key_col})
                DO UPDATE SET {value_col} = EXCLUDED.{value_col}
            WHERE {table}.{value_col} IS DISTINCT FROM EXCLUDED.{value_col};
        """).format(
            table=sql.Identifier(table),
            key_col=sql.Identifier(key_col),
            value_col=sql.Identifier(value_col),
        )
        self.cur.executemany(query, [(key, value) for key, value in code_map.items()])

    def add_location_refs(self, locations):
        self.cur.executemany("""
            INSERT INTO locations (tiploc, location_name, reservation_code, train_operator_code)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(tiploc)
            DO UPDATE SET
                location_name = EXCLUDED.location_name,
                reservation_code = EXCLUDED.reservation_code,
                train_operator_code = EXCLUDED.train_operator_code
            WHERE locations.location_name IS DISTINCT FROM EXCLUDED.location_name
                OR locations.reservation_code IS DISTINCT FROM EXCLUDED.reservation_code
                OR locations.train_operator_code IS DISTINCT FROM EXCLUDED.train_operator_code
            """, [(
                tpl,
                location.get('locname'),
                location.get('crs'),
                location.get('toc')
            ) for tpl, location in locations])

    def add_train_journeys(self, journeys):
        self.cur.executemany("""
            INSERT INTO train_journeys (rid, train_id, uid, scheduled_start, toc_code, status, is_passenger, cancelled, deleted, cancel_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (rid) DO UPDATE SET
                train_id = EXCLUDED.train_id,
                uid = EXCLUDED.uid,
                scheduled_start = EXCLUDED.scheduled_start,
                toc_code = EXCLUDED.toc_code,
                status = EXCLUDED.status,
                is_passenger = EXCLUDED.is_passenger,
                cancelled = EXCLUDED.cancelled,
                deleted = EXCLUDED.deleted,
                cancel_reason = EXCLUDED.cancel_reason
            """, [(
                rid,
                journey.get('train_id'),
                journey.get('uid'),
                journey.get('ssd'),
                journey.get('toc'),
                journey.get('status'),
                journey.get('passenger_service'),
                journey.get('cancelled'),
                journey.get('deleted'),
                journey.get('cancel_reason')
            ) for rid, journey in journeys])

    def add_train_stops(self, stops):
        self.cur.executemany("""
            INSERT INTO train_stops (rid, sequence, tiploc, location_type, activities, planned_activities, cancelled, platform, public_arrival, public_departure, working_arrival, working_departure, working_pass)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (rid, sequence) DO UPDATE SET
                tiploc = EXCLUDED.tiploc,
                location_type = EXCLUDED.location_type,
                activities = EXCLUDED.activities,
                planned_activities = EXCLUDED.planned_activities,
                cancelled = EXCLUDED.cancelled,
                platform = EXCLUDED.platform,
                public_arrival = EXCLUDED.public_arrival,
                public_departure = EXCLUDED.public_departure,
                working_arrival = EXCLUDED.working_arrival,
                working_departure = EXCLUDED.working_departure,
                working_pass = EXCLUDED.working_pass
        """, [(
            stop.get('rid'),
            stop.get('sequence'),
            stop.get('tiploc'),
            stop.get('location_type'),
            stop.get('activities'),
            stop.get('planned_activities'),
            stop.get('cancelled'),
            stop.get('platform'),
            stop.get('public_arrival'),
            stop.get('public_departure'),
            stop.get('working_arrival'),
            stop.get('working_departure'),
            stop.get('working_pass')
        ) for stop in stops])

    def commit(self):
        self.conn.commit()

    def close(self):
        self.cur.close()
        self.conn.close()
