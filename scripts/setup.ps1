# ==========================================================
#  Enclave — 地端一鍵安裝腳本 (P9-4) Windows 版
#  執行方式：在專案根目錄執行 .\scripts\setup.ps1
# ==========================================================
$ErrorActionPreference = "Stop"

function Info    { Write-Host "[Enclave] $args" -ForegroundColor Cyan }
function Success { Write-Host "  [✓] $args" -ForegroundColor Green }
function Warn    { Write-Host "  [!] $args" -ForegroundColor Yellow }
function Err     { Write-Host "  [✗] $args" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Enclave — 企業私有 AI 知識大腦  安裝程式" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ── 前置條件檢查 ──────────────────────────────────
Info "檢查前置條件..."

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Err "未安裝 Docker Desktop，請先至 https://www.docker.com 安裝"
}
Info "Docker 版本：$(docker --version)"
Success "前置條件通過"

# ── 環境設定 ──────────────────────────────────────
if (-not (Test-Path ".env")) {
    Info "建立 .env 設定檔..."
    Copy-Item ".env.example" ".env"

    # 自動產生 SECRET_KEY
    $secret = -join ((1..64) | ForEach-Object { "{0:x}" -f (Get-Random -Maximum 16) })
    (Get-Content ".env") -replace "change_this_to_a_secure_random_string_at_least_32_chars", $secret |
        Set-Content ".env" -Encoding UTF8
    Success "SECRET_KEY 已自動產生"

    Warn "請編輯 .env 設定以下必要項目："
    Warn "  - OPENAI_API_KEY（或改用 Ollama）"
    Warn "  - VOYAGE_API_KEY（向量搜尋）"
    Warn "  - FIRST_SUPERUSER_PASSWORD（管理員密碼）"
    Warn "  - POSTGRES_PASSWORD（資料庫密碼）"
    Write-Host ""
    Read-Host "設定完成後按 Enter 繼續"
} else {
    Info ".env 已存在，跳過建立"
}

# ── 環境檢查 ──────────────────────────────────────
Info "執行環境設定檢查..."
python scripts\check_env.py
if ($LASTEXITCODE -eq 1) {
    Warn "環境檢查有錯誤，請先修正 .env"
    Read-Host "確認已修正後按 Enter 繼續"
}

# ── 建立目錄 ──────────────────────────────────────
Info "建立所需目錄..."
New-Item -ItemType Directory -Force -Path "uploads", "logs" | Out-Null
Success "目錄建立完成"

# ── 啟動服務 ──────────────────────────────────────
Info "建置應用程式映像檔..."
docker compose build

Info "啟動所有服務..."
docker compose up -d

# ── 等待資料庫就緒 ────────────────────────────────
Info "等待資料庫就緒..."
$retry = 0
do {
    Start-Sleep -Seconds 2
    $retry++
    if ($retry -ge 30) { Err "資料庫啟動超時，請執行 docker compose logs db 查看原因" }
    $status = docker compose exec -T db pg_isready -U postgres 2>&1
} while ($LASTEXITCODE -ne 0)
Success "資料庫已就緒"

# ── 資料庫初始化 ──────────────────────────────────
Info "執行資料庫 Migration..."
docker compose exec -T web alembic upgrade head
Success "資料庫初始化完成"

Info "建立初始管理員帳號..."
docker compose exec -T web python scripts/initial_data.py
Success "管理員帳號已設定"

# ── 完成 ──────────────────────────────────────────
Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  Enclave 安裝完成！" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  前端介面：  http://localhost:3001"
Write-Host "  API 文件：  http://localhost:8001/docs"
Write-Host ""
Write-Host "  管理員帳號請查看 .env 中的 FIRST_SUPERUSER_EMAIL"
Write-Host ""
Write-Host "  常用指令："
Write-Host "  docker compose stop       # 停止服務"
Write-Host "  docker compose start      # 重新啟動"
Write-Host "  docker compose logs -f    # 查看即時日誌"
Write-Host ""
