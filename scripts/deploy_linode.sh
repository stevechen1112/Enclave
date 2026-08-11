#!/bin/bash
# ========================================================
# Enclave — Linode 一鍵部署腳本（2026-08 重寫版）
# ========================================================
# 用法：
#   bash scripts/deploy_linode.sh --ip 172.237.11.179
#   bash scripts/deploy_linode.sh --ip 172.237.11.179 --domain app.example.com
#   bash scripts/deploy_linode.sh --ip ... --repo https://github.com/you/enclave.git
#
# 前置條件：
#   1. Ubuntu 22.04/24.04，已安裝 Docker（curl -fsSL https://get.docker.com | sh）
#   2. 專案已 clone 至 /opt/enclave（或用 --repo 讓腳本 clone）
#   3. .env.production 已建立並填妥必填項（腳本會檢查）
# ========================================================

set -euo pipefail

# ── 參數解析 ──
IP=""
DOMAIN=""
REPO=""
APP_DIR="/opt/enclave"
SKIP_CONFIRM=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ip)       IP="$2"; shift 2 ;;
        --domain)   DOMAIN="$2"; shift 2 ;;
        --repo)     REPO="$2"; shift 2 ;;
        --dir)      APP_DIR="$2"; shift 2 ;;
        --yes)      SKIP_CONFIRM=true; shift ;;
        *) echo "未知參數: $1"; exit 1 ;;
    esac
done

if [[ -z "$IP" && -z "$DOMAIN" ]]; then
    echo "錯誤：必須提供 --ip 或 --domain"
    echo "範例：bash scripts/deploy_linode.sh --ip 172.237.11.179"
    exit 1
fi

# 未給正式網域時用 sslip.io
if [[ -z "$DOMAIN" ]]; then
    DOMAIN="app.$(echo "$IP" | tr '.' '-').sslip.io"
fi

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
step() { echo -e "\n${YELLOW}[$1/8] $2${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
die()  { echo -e "${RED}✗ $1${NC}"; exit 1; }

echo "========================================="
echo "Enclave — Linode 部署"
echo "目錄: $APP_DIR"
echo "網域: $DOMAIN"
echo "========================================="

# 1. 檢查必要工具
step 1 "檢查必要工具"
for cmd in docker git python3; do
    command -v $cmd &>/dev/null || die "$cmd 未安裝（Docker: curl -fsSL https://get.docker.com | sh）"
done
docker compose version &>/dev/null || die "docker compose plugin 不可用"
ok "工具齊全"

# 2. 取得專案
step 2 "準備專案目錄"
if [[ -d "$APP_DIR/.git" ]]; then
    cd "$APP_DIR"
    git pull --ff-only || echo -e "${YELLOW}警告：git pull 失敗，使用現有代碼${NC}"
elif [[ -n "$REPO" ]]; then
    git clone "$REPO" "$APP_DIR"
    cd "$APP_DIR"
elif [[ -f "$APP_DIR/docker-compose.prod.yml" ]]; then
    cd "$APP_DIR"
    echo "使用現有目錄（非 git repo）"
else
    die "找不到專案：請先 git clone 至 $APP_DIR，或用 --repo 指定"
fi
ok "專案就緒：$(pwd)"

# 3. 環境配置
step 3 "檢查 .env.production"
if [[ ! -f .env.production ]]; then
    cp .env.production.example .env.production
    python3 scripts/generate_secrets.py --output .env.production
    echo -e "${RED}.env.production 已從範本建立，請先編輯填入必填項後重跑：${NC}"
    echo "  vim $APP_DIR/.env.production"
    echo "  必填：OPENAI_API_KEY（或 GEMINI_API_KEY）、FIRST_SUPERUSER_EMAIL、FIRST_SUPERUSER_PASSWORD"
    exit 1
fi

# 必填項檢查
missing=()
grep -qE "^SECRET_KEY=\S{32,}" .env.production          || missing+=("SECRET_KEY")
grep -qE "^POSTGRES_PASSWORD=\S+" .env.production        || missing+=("POSTGRES_PASSWORD")
grep -qE "^REDIS_PASSWORD=\S+" .env.production           || missing+=("REDIS_PASSWORD")
grep -qE "^FIRST_SUPERUSER_EMAIL=\S+" .env.production    || missing+=("FIRST_SUPERUSER_EMAIL")
grep -qE "^FIRST_SUPERUSER_PASSWORD=\S{12,}" .env.production || missing+=("FIRST_SUPERUSER_PASSWORD(≥12字元)")
grep -qE "^(OPENAI_API_KEY|GEMINI_API_KEY)=\S+" .env.production || missing+=("OPENAI_API_KEY 或 GEMINI_API_KEY")
if [[ ${#missing[@]} -gt 0 ]]; then
    printf '%s\n' "${missing[@]}"
    die "上述必填項未設定"
fi

# MKA 旗標檢查（漏設會讓表單/知識卡消失）
for flag in FIXED_FORM_ENABLED KNOWHOW_CARD_ENABLED MODULE_ROUTER_ENABLED; do
    grep -qE "^${flag}=true" .env.production || echo -e "${YELLOW}警告：$flag 未設為 true，MKA 功能將被停用${NC}"
done

# 寫入網域相關設定
sed -i "s|^BACKEND_CORS_ORIGINS=.*|BACKEND_CORS_ORIGINS=http://${DOMAIN},https://${DOMAIN}|" .env.production
sed -i "s|^FRONTEND_URL=.*|FRONTEND_URL=http://${DOMAIN}|" .env.production
ok ".env.production 檢查通過，網域已設定為 $DOMAIN"

# 4. 防火牆
step 4 "設定防火牆（ufw）"
if command -v ufw &>/dev/null; then
    ufw allow 22/tcp  >/dev/null
    ufw allow 80/tcp  >/dev/null
    ufw allow 443/tcp >/dev/null
    ufw --force enable >/dev/null
    ok "ufw：22/80/443 已開放"
else
    echo "ufw 未安裝，跳過（請自行確認 80/443 對外開放）"
fi

# 5. 建置映像
step 5 "建置 Docker 映像（首次約 10–20 分鐘）"
docker compose -f docker-compose.prod.yml --env-file .env.production build
ok "映像建置完成"

# 6. 啟動服務
step 6 "啟動服務"
EMBED_PROFILE=""
if grep -qE "^EMBEDDING_PROVIDER=ollama" .env.production; then
    EMBED_PROFILE="--profile embed"
fi
docker compose -f docker-compose.prod.yml --env-file .env.production $EMBED_PROFILE up -d
echo "等待服務健康檢查（60 秒）..."
sleep 60
docker compose -f docker-compose.prod.yml ps
ok "服務已啟動"

# 7. Embedding 模型與資料庫初始化
step 7 "初始化（embedding 模型 / DB migration / 初始資料）"
if [[ -n "$EMBED_PROFILE" ]]; then
    if ! docker compose -f docker-compose.prod.yml exec -T ollama-embed ollama list 2>/dev/null | grep -q bge-m3; then
        echo "拉取 bge-m3 embedding 模型（約 1.2GB）..."
        docker compose -f docker-compose.prod.yml exec -T ollama-embed ollama pull bge-m3
    fi
    ok "bge-m3 就緒"
fi
docker compose -f docker-compose.prod.yml exec -T web alembic upgrade head
# .dockerignore 排除了 scripts/，映像內無此目錄 → 先複製進容器再執行
docker cp "$APP_DIR/scripts" "$(docker compose -f docker-compose.prod.yml ps -q web):/code/"
docker compose -f docker-compose.prod.yml exec -T -e PYTHONPATH=/code web python scripts/initial_data.py
ok "資料庫初始化完成"

# 8. 驗證
step 8 "部署驗證"
DOMAIN="$DOMAIN" PROTOCOL="http" APP_DIR="$APP_DIR" bash scripts/verify_deployment.sh || true

echo -e "\n${GREEN}=========================================${NC}"
echo -e "${GREEN}部署完成！${NC}"
echo -e "${GREEN}=========================================${NC}"
echo "  使用者介面: http://${DOMAIN}"
echo "  API 健康檢查: http://${DOMAIN}/health"
echo ""
echo "下一步："
echo "  1. 申請 SSL：certbot certonly --standalone -d ${DOMAIN}（先停 gateway）"
echo "     詳見 docs/LINODE_DEPLOYMENT.md §7"
echo "  2. 設定每日備份：crontab -e → 0 2 * * * cd $APP_DIR && bash scripts/backup.sh"
echo "  3. 日誌：docker compose -f docker-compose.prod.yml logs -f"
