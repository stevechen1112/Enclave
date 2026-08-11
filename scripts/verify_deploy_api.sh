#!/bin/bash
# 部署後 API 驗收：bootstrap + tasks
set -e
BASE="https://kachu.tw"
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login/access-token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=sales@demo.mka&password=Demo12345" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
echo "token_len=${#TOKEN}"

echo "=== /experience/bootstrap ==="
curl -s "$BASE/api/v1/experience/bootstrap" -H "Authorization: Bearer $TOKEN" | python3 -c '
import sys, json
d = json.load(sys.stdin)
print("keys=", list(d.keys()))
print("caps=", d.get("capabilities"))
print("default_home=", d.get("default_home"))
print("job_modules=", [m.get("module_key") for m in d.get("job_modules", [])])
print("workspace_entries=", len(d.get("workspace_entries", [])))
print("needs_job_role=", d.get("needs_job_role_assignment"))
ar = d.get("active_job_role") or {}
print("active_role=", ar.get("role_key"))
'

echo "=== /tasks ==="
curl -s "$BASE/api/v1/tasks" -H "Authorization: Bearer $TOKEN" | python3 -c '
import sys, json
d = json.load(sys.stdin)
if isinstance(d, list):
    print("task_count=", len(d))
    print("keys=", [t.get("task_key") for t in d])
else:
    print("resp=", d)
'
echo "VERIFY_DONE"
