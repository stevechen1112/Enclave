#!/bin/bash
# 驗證補強後的 parse-text：DEMO 例句應抓齊 customer/part_number/quantity/unit_price
set -e
BASE="https://kachu.tw"
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login/access-token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=sales@demo.mka&password=Demo12345" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

RESP=$(curl -s -X POST "$BASE/api/v1/tasks/quote/runs" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"idempotency_key":"verify-parse-'"$(date +%s)"'"}')
echo "start_run_resp=$(echo "$RESP" | head -c 300)"
RUN_ID=$(echo "$RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("id") or (d.get("run") or {}).get("id") or "")')
echo "run_id=$RUN_ID"

echo "=== parse-text（DEMO 例句）==="
curl -s -X POST "$BASE/api/v1/tasks/runs/$RUN_ID/parse-text" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"幫台中精機報價，料號 P-100，兩百個，單價一百二"}' | python3 -c '
import sys, json
d = json.load(sys.stdin)
print("detected_fields=", json.dumps(d.get("detected_fields"), ensure_ascii=False))
'
echo "PARSE_VERIFY_DONE"
