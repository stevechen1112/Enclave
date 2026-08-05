"""One-off: tombstone ALL golden scan docs (any status) to clear duplicates
before a clean re-ingest. Usage: python scripts/reset_golden_docs.py
"""
import httpx

GOLDEN_PREFIXES = ("000_", "001_", "002_", "003_", "005_", "006_",
                   "007_", "008_", "009_", "010_", "014_", "023_")

c = httpx.Client(base_url="http://localhost:8001", timeout=30)
r = c.post("/api/v1/auth/login/access-token",
           data={"username": "admin@example.com", "password": "admin123"})
r.raise_for_status()
c.headers["Authorization"] = "Bearer " + r.json()["access_token"]

items = c.get("/api/v1/documents/", params={"limit": 100}).json()
n = 0
for d in items:
    if d.get("filename", "").startswith(GOLDEN_PREFIXES) and not d.get("tombstoned_at"):
        resp = c.delete(f"/api/v1/documents/{d['id']}")
        print(resp.status_code, d["filename"], d["status"])
        n += 1
print("tombstoned:", n)
