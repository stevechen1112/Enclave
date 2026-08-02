"""Temporary probe: how many UNIQUE documents are behind the 83 / 39 counts?"""
import collections
import json
import os
import urllib.request

BASE = os.getenv("RAGFLOW_BASE_URL", "http://localhost:9380")
KEY = os.getenv("RAGFLOW_API_KEY", "")


def call(path):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


ds_id = call("/api/v1/datasets?page=1&page_size=50")["data"][0]["id"]
docs, page = [], 1
while True:
    batch = call(f"/api/v1/datasets/{ds_id}/documents?page={page}&page_size=100").get("data", {}).get("docs", [])
    if not batch:
        break
    docs.extend(batch)
    page += 1

groups = collections.defaultdict(list)
for d in docs:
    groups[(d.get("size"), d.get("type"))].append(d)

print(f"total docs = {len(docs)}   unique (size,type) = {len(groups)}")

zero_groups = {k: v for k, v in groups.items() if all(not d.get("chunk_count") for d in v)}
ok_groups = {k: v for k, v in groups.items() if any(d.get("chunk_count") for d in v)}
print(f"unique docs with ZERO chunks everywhere = {len(zero_groups)}")
print(f"unique docs with at least one good parse = {len(ok_groups)}")

print("\n--- UNIQUE zero-chunk documents (the real RF-01 target set) ---")
for (size, typ), v in sorted(zero_groups.items(), key=lambda x: -len(x[1])):
    msg = (v[0].get("progress_msg") or "").replace("\n", " ")
    reason = "no-text-layer" if "No chunk built" in msg else ("UNSTART" if v[0].get("run") == "UNSTART" else "other")
    print(f"  copies={len(v):>3} size={size:>9} type={typ:<5} reason={reason:<14} name={v[0].get('name')[:55]}")

print("\n--- duplication overview ---")
dup = collections.Counter(len(v) for v in groups.values())
for copies, n in sorted(dup.items()):
    print(f"  {n} unique doc(s) uploaded {copies}x")
