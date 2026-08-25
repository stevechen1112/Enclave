#!/bin/bash
# 生產冒煙驗證：code review 四項修正
BASE="https://kachu.tw"
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login/demo" \
  -H "Content-Type: application/json" \
  -d '{"persona":"sales"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

echo "=== 1. SSE stream chat（high 修正：generator 用獨立 session）==="
curl -s -N -X POST "$BASE/api/v1/chat/chat/stream" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"question":"報價單需要哪些欄位？","top_k":3}' \
  --max-time 60 | head -c 600
echo ""

echo "=== 2. forms validate（改走租戶 DB FormDefinition）==="
curl -s -X POST "$BASE/api/v1/forms/quote/validate" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"values":{"customer":"測試","part_number":"Q-200","quantity":300,"unit_price":250}}'
echo ""

echo "=== 3. approvals inbox（fail-closed 後仍正常回應）==="
curl -s -o /dev/null -w "approvals_inbox=%{http_code}\n" "$BASE/api/v1/approvals" -H "$AUTH"

echo "=== 4. bootstrap（needs_job_role_assignment 語意不變）==="
curl -s "$BASE/api/v1/experience/bootstrap" -H "$AUTH" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("modules:", len(d.get("job_modules") or []), "needs_assign:", d.get("needs_job_role_assignment"), "default_job_home:", d.get("default_job_home"))'
echo "SMOKE_DONE"
