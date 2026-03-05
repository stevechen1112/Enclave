"""
Creates a fresh demo tenant + demo user for live presentation.
Tenant: Enclave 現場展示公司 (completely empty, no documents)
User:   demo@enclave.local / admin123
"""
import urllib.request, urllib.parse, json

BASE = "http://api.172-237-5-254.sslip.io"
DEMO_EMAIL = "demo@enclave.local"
DEMO_PASS  = "admin123"
DEMO_TENANT = "Enclave 現場展示公司"

# ── 1. SU login ───────────────────────────────────────────
d = urllib.parse.urlencode({"username": "admin@example.com",
                             "password": "mcWzOEha0w7zKH9u53yG7Q"}).encode()
r = urllib.request.urlopen(urllib.request.Request(
    BASE + "/api/v1/auth/login/access-token", data=d, method="POST",
    headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=15)
su_token = json.loads(r.read())["access_token"]
print("SU login OK")

hdrs = {"Authorization": f"Bearer {su_token}", "Content-Type": "application/json"}

# ── 2. Create demo tenant ──────────────────────────────────
body = json.dumps({
    "name": DEMO_TENANT,
    "plan": "enterprise",
    "status": "active",
    "max_documents": 50,
    "max_storage_mb": 2048,
    "monthly_query_limit": 10000,
}).encode()
req = urllib.request.Request(BASE + "/api/v1/tenants/", data=body, method="POST", headers=hdrs)
try:
    r = urllib.request.urlopen(req, timeout=15)
    tenant = json.loads(r.read())
    print(f"Tenant created: {tenant['name']} / {tenant['id']}")
except urllib.error.HTTPError as e:
    err = e.read().decode()
    if "already exists" in err:
        # Fetch existing
        req2 = urllib.request.Request(BASE + "/api/v1/tenants/", headers={"Authorization": f"Bearer {su_token}"})
        r2 = urllib.request.urlopen(req2, timeout=10)
        tlist = json.loads(r2.read())
        tlist = tlist if isinstance(tlist, list) else tlist.get("items", tlist.get("data", []))
        tenant = next(t for t in tlist if t["name"] == DEMO_TENANT)
        print(f"Tenant already exists: {tenant['name']} / {tenant['id']}")
    else:
        raise

# ── 3. Create demo user ────────────────────────────────────
body = json.dumps({
    "email": DEMO_EMAIL,
    "password": DEMO_PASS,
    "full_name": "Demo 展示帳號",
    "tenant_id": tenant["id"],
    "role": "admin"
}).encode()
req = urllib.request.Request(BASE + "/api/v1/users/", data=body, method="POST", headers=hdrs)
try:
    r = urllib.request.urlopen(req, timeout=15)
    user = json.loads(r.read())
    print(f"User created: {user['email']} / role={user['role']}")
except urllib.error.HTTPError as e:
    err = e.read().decode()
    if "already exists" in err:
        print(f"User already exists: {DEMO_EMAIL} — OK")
    else:
        print(f"HTTP {e.code}: {err[:300]}")

# ── 4. Verify login ────────────────────────────────────────
d = urllib.parse.urlencode({"username": DEMO_EMAIL, "password": DEMO_PASS}).encode()
r = urllib.request.urlopen(urllib.request.Request(
    BASE + "/api/v1/auth/login/access-token", data=d, method="POST",
    headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=15)
resp = json.loads(r.read())
print("Login test:", "OK ✓" if resp.get("access_token") else "FAIL")
print()
print("=" * 50)
print(f"Demo 帳號: {DEMO_EMAIL}")
print(f"密碼:      {DEMO_PASS}")
print(f"租戶:      {DEMO_TENANT}")
print(f"文件:      空（可現場上傳展示）")
print("=" * 50)
