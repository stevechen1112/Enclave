import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import requests

base = "http://host.docker.internal:9380"
key = os.environ.get("RAGFLOW_API_KEY", "")
h = {"Authorization": f"Bearer {key}"}

ds = requests.get(base + "/api/v1/datasets", headers=h, params={"page_size": 100}).json()
for d in ds.get("data", []):
    resp = requests.get(
        base + f"/api/v1/datasets/{d['id']}/documents", headers=h, params={"page_size": 200}
    ).json()
    docs = (resp.get("data") or {}).get("docs") or []
    print(f"dataset {d.get('name')} ({d['id']}): {len(docs)} docs")
    for doc in docs:
        name = doc.get("name", "")
        print(
            f"  {name} | chunks={doc.get('chunk_count')} | tokens={doc.get('token_count')} "
            f"| run={doc.get('run')} | id={doc['id']}"
        )
