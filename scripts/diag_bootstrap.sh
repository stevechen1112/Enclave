#!/bin/bash
# 診斷 bootstrap 是否 500 及 web log
TOKEN=$(curl -s -X POST 'https://kachu.tw/api/v1/auth/login/access-token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=sales@demo.mka&password=Demo12345' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
echo "bootstrap_status:"
curl -s -o /tmp/boot.json -w '%{http_code}\n' 'https://kachu.tw/api/v1/experience/bootstrap' -H "Authorization: Bearer $TOKEN"
echo "--- bootstrap body (first 400) ---"
head -c 400 /tmp/boot.json
echo ""
echo "--- web recent errors ---"
docker compose -f /opt/enclave/docker-compose.prod.yml --env-file /opt/enclave/.env.production logs --tail=60 web 2>&1 | grep -iE 'error|exception|traceback' | tail -15
echo "DIAG_DONE"
