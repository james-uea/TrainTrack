import psycopg


def connect(database_url):
     conn = psycopg.connect(database_url)
     cur = conn.cursor()
     return conn, cur

def main():
    from dotenv import dotenv_values
    config = dotenv_values(".env")
    conn, cur = connect(config['DATABASE_URL'])
    cur.execute("SELECT version()")
    print(cur.fetchone())

if __name__ == "__main__":
    main()
