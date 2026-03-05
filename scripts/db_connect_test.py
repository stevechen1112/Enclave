import os
import psycopg2

host = os.environ.get("POSTGRES_SERVER", "db")
user = os.environ.get("POSTGRES_USER", "")
password = os.environ.get("POSTGRES_PASSWORD", "")
dbname = os.environ.get("POSTGRES_DB", "")

print(f"host={host} user={user} db={dbname} password_len={len(password)}")

conn = psycopg2.connect(host=host, user=user, password=password, dbname=dbname)
conn.close()
print("db connection ok")
