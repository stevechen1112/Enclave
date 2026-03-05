import urllib.request, urllib.parse, json

BASE = "http://api.172-237-5-254.sslip.io"

# Superuser login
d = urllib.parse.urlencode({"username": "admin@example.com", "password": "mcWzOEha0w7zKH9u53yG7Q"}).encode()
r = urllib.request.urlopen(urllib.request.Request(
    BASE + "/api/v1/auth/login/access-token", data=d, method="POST",
    headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=15)
su_token = json.loads(r.read())["access_token"]
print("SU login OK")

# Get tenant id
req = urllib.request.Request(BASE + "/api/v1/tenants/", headers={"Authorization": f"Bearer {su_token}"})
r = urllib.request.urlopen(req, timeout=10)
tenants = json.loads(r.read())
tlist = tenants if isinstance(tenants, list) else tenants.get("items", tenants.get("data", []))
tenant = next((t for t in tlist if "泰宇" in t.get("name", "")), None)
print(f"Tenant: {tenant['name']} / {tenant['id']}")

# Create steve user
body = json.dumps({
    "email": "steve@taiyutech.com",
    "password": "admin123",
    "full_name": "Steve",
    "tenant_id": tenant["id"],
    "role": "admin"
}).encode()
req = urllib.request.Request(
    BASE + "/api/v1/users/", data=body, method="POST",
    headers={"Authorization": f"Bearer {su_token}", "Content-Type": "application/json"})
try:
    r = urllib.request.urlopen(req, timeout=15)
    resp = json.loads(r.read())
    print(f"Created: {resp['email']} / role={resp['role']}")
except urllib.error.HTTPError as e:
    err = e.read().decode()
    if "already exists" in err:
        print("User already exists — OK")
    else:
        print(f"HTTP {e.code}: {err[:200]}")

# Verify login
d = urllib.parse.urlencode({"username": "steve@taiyutech.com", "password": "admin123"}).encode()
r = urllib.request.urlopen(urllib.request.Request(
    BASE + "/api/v1/auth/login/access-token", data=d, method="POST",
    headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=15)
resp = json.loads(r.read())
print("Login test:", "OK" if resp.get("access_token") else "FAIL")
