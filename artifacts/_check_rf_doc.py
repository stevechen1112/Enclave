import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import requests

base = "http://host.docker.internal:9380"
key = os.environ.get("RAGFLOW_API_KEY", "")
h = {"Authorization": f"Bearer {key}"}
DS = "599692668d0511f199eeb37ca37a0366"
DOC = "96ec4fec8f4011f180b77f0efc29850c"  # 巨大機械 from quality_report

import json

for label, doc_id in [("giant", DOC), ("tax113", "3eb749588f4011f180b77f0efc29850c")]:
    r = requests.get(base + f"/api/v1/datasets/{DS}/documents/{doc_id}/chunks",
                     headers=h, params={"page_size": 100})
    j = r.json()
    data = j.get("data") or {}
    chunks = data.get("chunks") or []
    doc = data.get("doc") or {}
    total = sum(len(c.get("content") or "") for c in chunks)
    print(f"== {label}: http={r.status_code} code={j.get('code')} "
          f"doc={doc.get('name')} run={doc.get('run')} "
          f"chunks={len(chunks)} total_chars={total}")
    if not chunks:
        print("   raw:", json.dumps(j, ensure_ascii=False)[:300])
