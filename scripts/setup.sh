#!/usr/bin/env bash
# ==========================================================
#  Enclave — 地端一鍵安裝腳本 (P9-4)
#  支援 Linux / macOS
#  執行方式：bash scripts/setup.sh
# ==========================================================
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()    { echo -e "${CYAN}[Enclave]${NC} $*"; }
success() { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }

echo ""
echo "=================================================="
echo "  Enclave — 企業私有 AI 知識大腦  安裝程式"
echo "=================================================="
echo ""

# ── 前置條件檢查 ──────────────────────────────────
info "檢查前置條件..."

command -v docker   &>/dev/null || error "未安裝 Docker，請先安裝 Docker Engine"
command -v docker compose &>/dev/null || \
  docker compose version &>/dev/null   || \
  error "未安裝 Docker Compose"

DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+')
info "Docker 版本：$DOCKER_VERSION"
success "前置條件通過"

# ── 環境設定 ──────────────────────────────────────
if [ ! -f ".env" ]; then
    info "建立 .env 設定檔..."
    cp .env.example .env

    # 自動產生安全隨機金鑰
    if command -v python3 &>/dev/null; then
        SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
        sed -i "s|change_this_to_a_secure_random_string_at_least_32_chars|$SECRET|g" .env
        success "SECRET_KEY 已自動產生"
    else
        warn "無法自動產生 SECRET_KEY，請手動修改 .env 中的 SECRET_KEY"
    fi

    warn "請編輯 .env 設定以下必要項目："
    warn "  - OPENAI_API_KEY（或改用 Ollama）"
    warn "  - VOYAGE_API_KEY（向量搜尋）"
    warn "  - FIRST_SUPERUSER_PASSWORD（管理員密碼）"
    warn "  - POSTGRES_PASSWORD（資料庫密碼）"
    echo ""
    read -p "設定完成後按 Enter 繼續，或 Ctrl+C 離開先編輯 .env ..."
else
    info ".env 已存在，跳過建立"
fi

# ── 環境檢查 ──────────────────────────────────────
info "執行環境設定檢查..."
python3 scripts/check_env.py || {
    warn "環境檢查有問題，請先修正 .env 再繼續"
    read -p "確認已修正後按 Enter 繼續，或 Ctrl+C 離開..."
}

# ── 建立目錄 ──────────────────────────────────────
info "建立所需目錄..."
mkdir -p uploads logs
success "目錄建立完成"

# ── 啟動服務 ──────────────────────────────────────
info "拉取 Docker 映像檔（首次執行較慢，請耐心等待）..."
docker compose pull --quiet db redis 2>/dev/null || true

info "建置應用程式映像檔..."
docker compose build --quiet

info "啟動所有服務..."
docker compose up -d

# ── 等待資料庫就緒 ────────────────────────────────
info "等待資料庫就緒..."
RETRY=0; MAX_RETRY=30
until docker compose exec -T db pg_isready -U postgres -q 2>/dev/null; do
    RETRY=$((RETRY + 1))
    [ $RETRY -ge $MAX_RETRY ] && error "資料庫啟動超時，請執行 docker compose logs db 查看原因"
    sleep 2
done
success "資料庫已就緒"

# ── 資料庫初始化 ──────────────────────────────────
info "執行資料庫 Migration..."
docker compose exec -T web alembic upgrade head
success "資料庫初始化完成"

info "建立初始管理員帳號..."
docker compose exec -T web python scripts/initial_data.py || warn "管理員帳號可能已存在，跳過"
success "管理員帳號已設定"

# ── 完成 ──────────────────────────────────────────
echo ""
echo "=================================================="
echo -e "  ${GREEN}Enclave 安裝完成！${NC}"
echo "=================================================="
echo ""
echo "  🌐 前端介面：  http://localhost:3001"
echo "  📡 API 文件：  http://localhost:8001/docs"
echo ""
echo "  管理員帳號請查看 .env 中的 FIRST_SUPERUSER_EMAIL"
echo ""
echo "  常用指令："
echo "  docker compose stop       # 停止服務"
echo "  docker compose start      # 重新啟動"
echo "  docker compose logs -f    # 查看即時日誌"
echo ""
