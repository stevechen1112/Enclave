#!/bin/bash
# ========================================================
# Enclave — 部署驗證腳本（2026-08 對外版）
# ========================================================
# 使用方式：
#   bash scripts/verify_deployment.sh
#   DOMAIN=app.example.com PROTOCOL=https bash scripts/verify_deployment.sh
#
# 檢查項目：容器狀態 → 對外端點 → 登入與 MKA 路由 → 基礎設施
# ========================================================

DOMAIN="${DOMAIN:-localhost}"
PROTOCOL="${PROTOCOL:-http}"
APP_DIR="${APP_DIR:-/opt/enclave}"
BASE="${PROTOCOL}://${DOMAIN}"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
PASS=0; FAIL=0

check() {
    local name=$1 url=$2 expected=${3:-200}
    echo -n "檢查 ${name}... "
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null || echo "000")
    if [[ "$code" == "$expected" ]]; then
        echo -e "${GREEN}✓ (${code})${NC}"; ((PASS++))
    else
        echo -e "${RED}✗ (${code}，預期 ${expected})${NC}"; ((FAIL++))
    fi
}

echo "========================================="
echo "Enclave — 部署驗證（${BASE}）"
echo "========================================="

cd "$APP_DIR" 2>/dev/null || cd "$(dirname "$0")/.."

# 1. 容器狀態
echo -e "\n${YELLOW}[1/4] 容器狀態${NC}"
$COMPOSE ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || $COMPOSE ps
unhealthy=$($COMPOSE ps 2>/dev/null | grep -ciE "unhealthy|restarting|exited" || true)
if [[ "$unhealthy" -gt 0 ]]; then
    echo -e "${RED}✗ 有 ${unhealthy} 個容器狀態異常${NC}"; ((FAIL++))
else
    echo -e "${GREEN}✓ 容器狀態正常${NC}"; ((PASS++))
fi

# 2. 對外端點
echo -e "\n${YELLOW}[2/4] 對外端點${NC}"
check "前端 SPA"            "${BASE}/"
check "API 健康檢查"        "${BASE}/health"
# gateway 設定檔把 /docs 與 openapi.json 擋下；若未經 gateway（直打 8000）則略過
check "API docs 已封鎖"     "${BASE}/docs" 403
check "openapi.json 已封鎖" "${BASE}/api/v1/openapi.json" 403
check "未授權 API 拒絕"     "${BASE}/api/v1/users/me" 401

# 3. 登入與 MKA 路由（用超級管理員 token 驗證）
echo -e "\n${YELLOW}[3/4] 登入與 MKA 功能路由${NC}"
SU_EMAIL=$(grep -E "^FIRST_SUPERUSER_EMAIL=" .env.production | cut -d= -f2-)
SU_PASS=$(grep -E "^FIRST_SUPERUSER_PASSWORD=" .env.production | cut -d= -f2-)
TOKEN=$(curl -s --max-time 15 -X POST "${BASE}/api/v1/auth/login/access-token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=${SU_EMAIL}&password=${SU_PASS}" | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

if [[ -z "$TOKEN" ]]; then
    echo -e "${RED}✗ 超級管理員登入失敗（${SU_EMAIL}）${NC}"; ((FAIL++))
else
    echo -e "${GREEN}✓ 超級管理員登入成功${NC}"; ((PASS++))
    auth=(-H "Authorization: Bearer ${TOKEN}")
    for route in "/api/v1/job-modules" "/api/v1/forms" "/api/v1/knowhow" "/api/v1/job-roles" "/api/v1/approvals/inbox"; do
        echo -n "檢查 ${route}... "
        code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${auth[@]}" "${BASE}${route}" 2>/dev/null || echo "000")
        if [[ "$code" == "200" ]]; then
            echo -e "${GREEN}✓${NC}"; ((PASS++))
        else
            echo -e "${RED}✗ (${code})${NC}"; ((FAIL++))
        fi
    done
fi

# 4. 基礎設施
echo -e "\n${YELLOW}[4/4] 基礎設施${NC}"
echo -n "PostgreSQL... "
$COMPOSE exec -T db pg_isready -q \
    && echo -e "${GREEN}✓${NC}" && ((PASS++)) || { echo -e "${RED}✗${NC}"; ((FAIL++)); }
echo -n "Redis... "
REDIS_PW=$(grep -E "^REDIS_PASSWORD=" .env.production | cut -d= -f2-)
$COMPOSE exec -T redis redis-cli -a "$REDIS_PW" ping 2>/dev/null | grep -q PONG \
    && echo -e "${GREEN}✓${NC}" && ((PASS++)) || { echo -e "${RED}✗${NC}"; ((FAIL++)); }
if $COMPOSE ps 2>/dev/null | grep -q ollama-embed; then
    echo -n "Ollama embedding（bge-m3）... "
    $COMPOSE exec -T ollama-embed ollama list 2>/dev/null | grep -q bge-m3 \
        && echo -e "${GREEN}✓${NC}" && ((PASS++)) || { echo -e "${RED}✗${NC}"; ((FAIL++)); }
fi

echo ""
echo "========================================="
if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}✓ 全部通過（${PASS} 項）${NC}"
    echo "系統已上線：${BASE}"
else
    echo -e "${RED}✗ ${PASS} 通過 / ${FAIL} 失敗${NC}"
    echo "排查：$COMPOSE logs --tail=100 web worker"
    exit 1
fi
