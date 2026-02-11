#!/bin/bash
# ========================================================
# UniHR SaaS — 部署驗證腳本
# ========================================================
# 檢查所有服務是否正常運行
# ========================================================

set -e

IP="172.237.11.179"
DOMAIN="172-237-11-179.sslip.io"
PROTOCOL="http"  # 初次部署使用 HTTP，配置 SSL 後改為 https

# 顏色定義
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "========================================="
echo "UniHR SaaS - 部署驗證"
echo "========================================="
echo ""

# 計數器
PASS=0
FAIL=0

# 檢查函數
check_service() {
    local name=$1
    local url=$2
    local expected_code=${3:-200}
    
    echo -n "檢查 ${name}... "
    
    response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${url}" 2>&1 || echo "000")
    
    if [ "$response" -eq "$expected_code" ]; then
        echo -e "${GREEN}✓ OK (${response})${NC}"
        ((PASS++))
    else
        echo -e "${RED}✗ FAIL (${response})${NC}"
        ((FAIL++))
    fi
}

# 1. Docker 服務狀態
echo -e "${YELLOW}[1/3] Docker 服務狀態${NC}"
echo "---------------------------------------"
cd /opt/aihr
docker compose -f docker-compose.prod.yml ps
echo ""

# 2. 健康檢查端點
echo -e "${YELLOW}[2/3] API 健康檢查${NC}"
echo "---------------------------------------"
check_service "Backend API Health" "${PROTOCOL}://api.${DOMAIN}/health"
check_service "Backend API Docs" "${PROTOCOL}://api.${DOMAIN}/docs"
echo ""

# 3. 前端介面
echo -e "${YELLOW}[3/3] 前端介面${NC}"
echo "---------------------------------------"
check_service "使用者介面 (app)" "${PROTOCOL}://app.${DOMAIN}"
check_service "系統方介面 (admin)" "${PROTOCOL}://admin.${DOMAIN}"
check_service "Grafana" "${PROTOCOL}://grafana.${DOMAIN}" "302"
echo ""

# 4. DNS 解析檢查
echo -e "${YELLOW}[額外] DNS 解析檢查${NC}"
echo "---------------------------------------"
for subdomain in app admin api admin-api grafana; do
    echo -n "檢查 ${subdomain}.${DOMAIN}... "
    result=$(dig +short ${subdomain}.${DOMAIN} | tail -n1)
    if [ "$result" = "$IP" ]; then
        echo -e "${GREEN}✓ ${result}${NC}"
    else
        echo -e "${RED}✗ ${result} (預期: ${IP})${NC}"
    fi
done
echo ""

# 5. 資料庫連線檢查
echo -e "${YELLOW}[額外] 資料庫連線${NC}"
echo "---------------------------------------"
echo -n "PostgreSQL... "
if docker compose -f docker-compose.prod.yml exec -T postgres pg_isready -q; then
    echo -e "${GREEN}✓ OK${NC}"
else
    echo -e "${RED}✗ FAIL${NC}"
fi

echo -n "Redis... "
REDIS_PASSWORD=$(grep REDIS_PASSWORD= .env.production | cut -d '=' -f2)
if docker compose -f docker-compose.prod.yml exec -T redis redis-cli -a "$REDIS_PASSWORD" ping | grep -q PONG; then
    echo -e "${GREEN}✓ OK${NC}"
else
    echo -e "${RED}✗ FAIL${NC}"
fi
echo ""

# 總結
echo "========================================="
if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}✓ 所有檢查通過！(${PASS}/${PASS})${NC}"
    echo -e "${GREEN}部署完全正常！${NC}"
else
    echo -e "${RED}✗ 部分檢查失敗 (${PASS} 通過 / ${FAIL} 失敗)${NC}"
    echo -e "${YELLOW}請檢查：${NC}"
    echo "  1. docker compose -f docker-compose.prod.yml logs"
    echo "  2. 防火牆設定（ufw status）"
    echo "  3. .env.production 配置是否正確"
fi
echo "========================================="
echo ""

# 使用指南
echo -e "${YELLOW}存取網址：${NC}"
echo "  使用者介面: ${PROTOCOL}://app.${DOMAIN}"
echo "  系統方介面: ${PROTOCOL}://admin.${DOMAIN}"
echo "  API 文件: ${PROTOCOL}://api.${DOMAIN}/docs"
echo "  Grafana: ${PROTOCOL}://grafana.${DOMAIN}"
echo ""
echo -e "${YELLOW}登入資訊：${NC}"
echo "  超級管理員: $(grep FIRST_SUPERUSER_EMAIL= .env.production | cut -d '=' -f2)"
echo "  密碼: 見 .env.production"
echo ""
echo -e "${YELLOW}Grafana 登入：${NC}"
echo "  帳號: admin"
echo "  密碼: $(grep GRAFANA_PASSWORD= .env.production | cut -d '=' -f2)"
echo ""
