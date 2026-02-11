#!/bin/bash
# ========================================================
# UniHR SaaS — Linode 快速部署腳本
# ========================================================
# IP: 172.237.11.179
# 使用 sslip.io 臨時網域
# ========================================================

set -e  # 遇到錯誤立即停止

echo "========================================="
echo "UniHR SaaS - Linode 部署開始"
echo "========================================="

# 顏色定義
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 1. 檢查必要工具
echo -e "${YELLOW}[1/8] 檢查必要工具...${NC}"
for cmd in docker git python3; do
    if ! command -v $cmd &> /dev/null; then
        echo -e "${RED}錯誤: $cmd 未安裝${NC}"
        exit 1
    fi
done
echo -e "${GREEN}✓ 必要工具已安裝${NC}"

# 2. Clone 或更新專案
echo -e "${YELLOW}[2/8] 下載專案...${NC}"
if [ -d "/opt/aihr" ]; then
    echo "專案已存在，更新中..."
    cd /opt/aihr
    git pull
else
    echo "Clone 專案..."
    cd /opt
    git clone https://github.com/stevechen1112/aihr.git
    cd /opt/aihr
fi
echo -e "${GREEN}✓ 專案已準備${NC}"

# 3. 生成環境配置
echo -e "${YELLOW}[3/8] 生成環境配置...${NC}"
if [ -f ".env.production" ]; then
    echo -e "${YELLOW}警告: .env.production 已存在，備份為 .env.production.backup${NC}"
    cp .env.production .env.production.backup
fi

python3 scripts/generate_secrets.py --output .env.production
echo -e "${GREEN}✓ 環境配置已生成${NC}"

# 4. 更新 .env.production 使用 sslip.io 網域
echo -e "${YELLOW}[4/8] 配置 sslip.io 網域...${NC}"
IP="172.237.11.179"
DOMAIN="172-237-11-179.sslip.io"

# 更新 CORS
sed -i "s|BACKEND_CORS_ORIGINS=.*|BACKEND_CORS_ORIGINS=http://app.${DOMAIN},http://admin.${DOMAIN}|g" .env.production

# 添加 Frontend URLs（如果不存在）
if ! grep -q "FRONTEND_URL=" .env.production; then
    echo "FRONTEND_URL=http://app.${DOMAIN}" >> .env.production
fi
if ! grep -q "ADMIN_FRONTEND_URL=" .env.production; then
    echo "ADMIN_FRONTEND_URL=http://admin.${DOMAIN}" >> .env.production
fi

echo -e "${GREEN}✓ 網域配置完成${NC}"
echo -e "${YELLOW}使用網域:${NC}"
echo -e "  - 使用者介面: http://app.${DOMAIN}"
echo -e "  - 系統方介面: http://admin.${DOMAIN}"
echo -e "  - API: http://api.${DOMAIN}"
echo -e "  - Grafana: http://grafana.${DOMAIN}"

# 5. 手動配置提示
echo -e "${YELLOW}[5/8] 請手動配置以下必填項目...${NC}"
echo -e "${RED}請使用編輯器打開 .env.production 並填入：${NC}"
echo "  1. OPENAI_API_KEY"
echo "  2. VOYAGE_API_KEY"
echo "  3. LLAMAPARSE_API_KEY (如果使用)"
echo "  4. FIRST_SUPERUSER_EMAIL"
echo "  5. FIRST_SUPERUSER_PASSWORD"
echo ""
echo -e "${YELLOW}按 Enter 繼續（完成編輯後）...${NC}"
read

# 6. 配置 Gateway（使用 sslip.io 版本）
echo -e "${YELLOW}[6/8] 配置 Nginx Gateway...${NC}"
if [ -f "nginx/gateway.conf.sslip" ]; then
    cp nginx/gateway.conf.sslip nginx/gateway.conf.active
    echo -e "${GREEN}✓ Gateway 配置已更新（HTTP 模式，SSL 待配置）${NC}"
else
    echo -e "${YELLOW}警告: nginx/gateway.conf.sslip 不存在，使用預設 gateway.conf${NC}"
    cp nginx/gateway.conf nginx/gateway.conf.active
fi

# 7. 啟動服務
echo -e "${YELLOW}[7/8] 啟動 Docker 服務...${NC}"
docker compose -f docker-compose.prod.yml --env-file .env.production up -d

echo "等待服務啟動..."
sleep 15

# 檢查服務狀態
docker compose -f docker-compose.prod.yml ps

# 8. 初始化資料庫
echo -e "${YELLOW}[8/8] 初始化資料庫...${NC}"
echo "執行資料庫遷移..."
docker compose -f docker-compose.prod.yml exec -T web alembic upgrade head

echo "創建初始租戶與超級管理員..."
docker compose -f docker-compose.prod.yml exec -T web python scripts/initial_data.py

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}✓ 部署完成！${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo -e "${YELLOW}存取網址（HTTP）：${NC}"
echo -e "  使用者介面: http://app.${DOMAIN}"
echo -e "  系統方介面: http://admin.${DOMAIN}"
echo -e "  API 文件: http://api.${DOMAIN}/docs"
echo -e "  Grafana: http://grafana.${DOMAIN}"
echo ""
echo -e "${YELLOW}下一步（可選）：${NC}"
echo "  1. 配置 SSL 憑證（Certbot + Let's Encrypt）"
echo "     詳見：docs/LINODE_DEPLOYMENT.md § 7"
echo "  2. IP 白名單管理介面（建議啟用）"
echo "  3. 設定自動備份（scripts/backup.sh）"
echo ""
echo -e "${YELLOW}查看日誌：${NC}"
echo "  docker compose -f docker-compose.prod.yml logs -f"
echo ""
echo -e "${YELLOW}常用指令：${NC}"
echo "  重啟服務: docker compose -f docker-compose.prod.yml restart"
echo "  停止服務: docker compose -f docker-compose.prod.yml stop"
echo "  查看狀態: docker compose -f docker-compose.prod.yml ps"
echo ""
echo -e "${GREEN}部署完成！${NC}"
