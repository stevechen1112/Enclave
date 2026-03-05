#!/bin/bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=demo@enclave.local&password=admin123' | \
  python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

echo "Token obtained: ${TOKEN:0:20}..."
STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/chat/dashboard/rag)
echo "RAG dashboard status: $STATUS"

STATUS2=$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/audit/usage/by-action)
echo "Audit usage/by-action status: $STATUS2"
