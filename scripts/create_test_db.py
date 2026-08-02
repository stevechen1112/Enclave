"""Create test database if not exists."""
import psycopg2

conn = psycopg2.connect(
    host='localhost', port=5435,
    user='postgres', password='postgres',
    dbname='postgres'
)
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname='enclave_test'")
if cur.fetchone() is None:
    cur.execute('CREATE DATABASE enclave_test')
    print('Created enclave_test')
else:
    print('enclave_test already exists')
cur.close()
conn.close()
