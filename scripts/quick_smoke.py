"""Quick smoketest with JWT auth."""
import httpx
import sys

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE4MTcwNTYwNDMsInN1YiI6InNtb2tldGVzdEBlbmNsYXZlLmxvY2FsIiwidGVuYW50X2lkIjoiMDllZTkzNTItYjA3Mi00OWI4LThkNTYtN2Q0YjYwZmQ0YzY2In0.TwGrSQZEwQeSYGoN2Ws557LPhqOfcWC29O1wtP94F74"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
ENCLAVE = "http://localhost:8000"
RAGFLOW = "http://localhost:9380"
WEKNORA = "http://localhost:8081"

ok = 0
total = 0

def check(name, r, expect=200):
    global ok, total
    total += 1
    expected = expect if isinstance(expect, (list, tuple)) else [expect]
    if r.status_code in expected:
        ok += 1
        print(f"  PASS {name}: {r.status_code}")
    else:
        print(f"  FAIL {name}: {r.status_code} {r.text[:100]}")

# 1. Gateway
r = httpx.get(f"{ENCLAVE}/api/v1/gateway/health", timeout=10)
check("Gateway health", r)

# 2. RAGFlow
r = httpx.get(f"{RAGFLOW}/api/v1/system/healthz", timeout=10)
check("RAGFlow health", r)

# 3. WeKnora
r = httpx.get(f"{WEKNORA}/health", timeout=10)
check("WeKnora health", r)

# 4. List documents
r = httpx.get(f"{ENCLAVE}/api/v1/documents/", headers=HEADERS, timeout=10)
check("List documents", r)

# 5. Upload
with open("test-data/sample_manual.pdf", "rb") as f:
    r = httpx.post(f"{ENCLAVE}/api/v1/documents/upload", headers=HEADERS, files={"file": ("sample_manual.pdf", f, "application/pdf")}, timeout=30)
check("Upload PDF", r, expect=(200, 201))

# 6. List after upload
r = httpx.get(f"{ENCLAVE}/api/v1/documents/", headers=HEADERS, timeout=10)
docs = r.json() if r.status_code == 200 else []
check("List after upload", r)
if docs:
    print(f"    Documents: {len(docs)}")

print(f"\n{ok}/{total} passed")
sys.exit(0 if ok == total else 1)
