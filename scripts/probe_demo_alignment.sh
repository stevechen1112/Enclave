#!/bin/bash
set -e
BASE="https://kachu.tw"
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login/demo" \
  -H "Content-Type: application/json" \
  -d '{"persona":"sales"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

curl -s "$BASE/api/v1/experience/bootstrap" -H "$AUTH" > /tmp/boot.json
curl -s "$BASE/api/v1/tasks/definitions" -H "$AUTH" > /tmp/defs.json
curl -s -X POST "$BASE/api/v1/tasks/quote/runs" -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"idempotency_key\":\"demo-align-$(date +%s)-$RANDOM\"}" > /tmp/start.json
RUN_ID=$(python3 -c 'import json;print(json.load(open("/tmp/start.json")).get("id",""))')
echo "run_id=$RUN_ID"
curl -s -X POST "$BASE/api/v1/tasks/runs/${RUN_ID}/parse-text" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"text":"幫翔展科技報價，料號 P-200，三百個，單價一千一百五十"}' > /tmp/parse.json

# also try Chinese numeral sentence used in UI example
curl -s -X POST "$BASE/api/v1/tasks/quote/runs" -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"idempotency_key\":\"demo-align-b-$(date +%s)-$RANDOM\"}" > /tmp/start2.json
RUN2=$(python3 -c 'import json;print(json.load(open("/tmp/start2.json")).get("id",""))')
curl -s -X POST "$BASE/api/v1/tasks/runs/${RUN2}/parse-text" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"text":"幫台中精機報價，料號 P-100，兩百個，單價一百二"}' > /tmp/parse2.json

python3 <<'PY'
import json
boot = json.load(open("/tmp/boot.json"))
print("=== sales bootstrap workspace ===")
for e in boot.get("workspace_entries") or []:
    print(f"  {e.get('label')} -> {e.get('path')}")
print("=== defs raw type ===", type(json.load(open("/tmp/defs.json"))).__name__)
defs = json.load(open("/tmp/defs.json"))
print("defs sample:", str(defs)[:300])
print("=== parse1 (翔展) ===")
p = json.load(open("/tmp/parse.json"))
print(str(p)[:600])
print("=== parse2 (台中精機 UI 範例) ===")
p2 = json.load(open("/tmp/parse2.json"))
vals = (p2.get("input_snapshot") or {}).get("values") if isinstance(p2, dict) else None
print("values:", vals)
print("DONE")
PY
