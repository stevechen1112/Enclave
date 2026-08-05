import psycopg2

conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5435/enclave")
cur = conn.cursor()
cur.execute(
    "SELECT count(*), bool_and(relrowsecurity), bool_and(NOT relforcerowsecurity) "
    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
    "WHERE n.nspname='public' AND c.relrowsecurity"
)
total, all_rls, none_forced = cur.fetchone()
print(f"RLS tables: {total}, all enabled: {all_rls}, none forced (shadow): {none_forced}")
cur.execute("SELECT count(*) FROM pg_policies WHERE policyname='tenant_isolation'")
print(f"tenant_isolation policies: {cur.fetchone()[0]}")
cur.execute("SELECT tablename FROM pg_policies WHERE policyname='tenant_isolation' ORDER BY tablename")
print("tables:", ", ".join(r[0] for r in cur.fetchall()))
conn.close()
