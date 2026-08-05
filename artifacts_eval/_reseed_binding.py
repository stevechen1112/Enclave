"""用 .env 的部署級 sidecar ID 補種 binding（migration 在無 env 的 shell 跑過，種子為 NULL）。

單租戶部署語意：所有現有租戶共享本部署的 sidecar dataset／KB。
僅更新目前為 NULL 的列，不覆蓋已有值（未來 Form C 的 per-tenant 歸屬）。
"""
import psycopg2

DATASET = "599692668d0511f199eeb37ca37a0366"
KB = "0c1eb831-7a17-4f87-9a52-51f2b64a1e02"

conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5435/enclave")
conn.autocommit = True
cur = conn.cursor()
cur.execute(
    "UPDATE tenant_sidecar_bindings SET ragflow_dataset_id = %s WHERE ragflow_dataset_id IS NULL",
    (DATASET,),
)
print(f"dataset backfilled: {cur.rowcount}")
cur.execute(
    "UPDATE tenant_sidecar_bindings SET weknora_kb_id = %s WHERE weknora_kb_id IS NULL",
    (KB,),
)
print(f"kb backfilled: {cur.rowcount}")
cur.execute(
    "SELECT count(*), bool_and(ragflow_dataset_id IS NOT NULL), bool_and(weknora_kb_id IS NOT NULL) "
    "FROM tenant_sidecar_bindings"
)
total, ds_ok, kb_ok = cur.fetchone()
print(f"bindings={total} all_have_dataset={ds_ok} all_have_kb={kb_ok}")
conn.close()
