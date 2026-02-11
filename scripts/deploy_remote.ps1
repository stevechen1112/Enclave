# ========================================================
# 遠端部署腳本 (Windows PowerShell)
# ========================================================
# 用途：從本地一鍵觸發 Linode 伺服器部署
# 前置：需先執行 .\scripts\setup_ssh_key.ps1 設定免密碼登入
# ========================================================

param(
    [string]$ServerHost = "aihr-linode",  # 使用 SSH config 中的別名
    [string]$ServerIP = "172.237.11.179",
    [string]$Username = "root",
    [string]$ProjectPath = "/opt/aihr",
    [switch]$SkipGitPush,                 # 跳過 Git push
    [switch]$FullDeploy,                  # 完整部署（重建容器）
    [switch]$RestartOnly                  # 僅重啟服務
)

$SSHKeyPath = "$env:USERPROFILE\.ssh\id_rsa_linode"

# 顏色函數
function Write-Step {
    param([string]$Message)
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

function Write-Warning-Custom {
    param([string]$Message)
    Write-Host "⚠ $Message" -ForegroundColor Yellow
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "UniHR SaaS - 遠端部署工具" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 檢查 SSH 密鑰
if (-not (Test-Path $SSHKeyPath)) {
    Write-Error-Custom "SSH 密鑰不存在: $SSHKeyPath"
    Write-Host "請先執行: .\scripts\setup_ssh_key.ps1" -ForegroundColor Yellow
    exit 1
}

# 2. 測試 SSH 連線
Write-Step "測試 SSH 連線..."
$TestConnection = ssh -i $SSHKeyPath -o ConnectTimeout=5 "$Username@$ServerIP" "echo 'ok'" 2>&1
if ($TestConnection -ne "ok") {
    Write-Error-Custom "無法連線到伺服器 $ServerIP"
    Write-Host "請檢查："
    Write-Host "  1. 伺服器是否在線"
    Write-Host "  2. SSH 密鑰是否正確設定"
    Write-Host "  3. 執行 .\scripts\setup_ssh_key.ps1 重新設定"
    exit 1
}
Write-Success "SSH 連線正常"

# 3. 推送本地更改到 GitHub（可選）
if (-not $SkipGitPush) {
    Write-Step "檢查 Git 狀態..."
    git fetch origin main 2>&1 | Out-Null
    $GitStatus = git status --porcelain
    
    if ($GitStatus) {
        Write-Warning-Custom "有未提交的更改"
        $PushChoice = Read-Host "是否提交並推送到 GitHub? (y/N)"
        if ($PushChoice -eq "y" -or $PushChoice -eq "Y") {
            Write-Step "提交更改..."
            $CommitMessage = Read-Host "請輸入 commit 訊息（直接 Enter 使用預設）"
            if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
                $CommitMessage = "Deploy: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
            }
            
            git add -A
            git commit -m $CommitMessage
            git push origin main
            
            if ($LASTEXITCODE -eq 0) {
                Write-Success "程式碼已推送到 GitHub"
            } else {
                Write-Error-Custom "Git push 失敗"
                exit 1
            }
        }
    } else {
        Write-Success "沒有未提交的更改"
    }
}

# 4. 部署腳本內容
$DeployScript = @'
#!/bin/bash
set -e

echo "========================================="
echo "開始部署..."
echo "========================================="

cd /opt/aihr

# 拉取最新代碼
echo "[1/5] 拉取最新代碼..."
git fetch origin main
git reset --hard origin/main
echo "✓ 代碼已更新"

# 檢查 .env.production
echo "[2/5] 檢查環境配置..."
if [ ! -f ".env.production" ]; then
    echo "✗ .env.production 不存在！"
    echo "請先執行初始部署或手動創建該檔案"
    exit 1
fi
echo "✓ 環境配置存在"

# 處理部署模式
DEPLOY_MODE="$1"

if [ "$DEPLOY_MODE" = "restart-only" ]; then
    echo "[3/5] 僅重啟服務（跳過構建）..."
    docker compose -f docker-compose.prod.yml --env-file .env.production restart
    echo "✓ 服務已重啟"
    
elif [ "$DEPLOY_MODE" = "full" ]; then
    echo "[3/5] 完整部署（重建容器）..."
    docker compose -f docker-compose.prod.yml --env-file .env.production down
    docker compose -f docker-compose.prod.yml --env-file .env.production build --no-cache
    docker compose -f docker-compose.prod.yml --env-file .env.production up -d
    echo "✓ 容器已重建"
    
else
    echo "[3/5] 更新並重啟服務..."
    docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
    echo "✓ 服務已更新"
fi

# 資料庫遷移
echo "[4/5] 執行資料庫遷移..."
sleep 5  # 等待服務啟動
docker compose -f docker-compose.prod.yml exec -T web alembic upgrade head
echo "✓ 資料庫遷移完成"

# 檢查服務狀態
echo "[5/5] 檢查服務狀態..."
docker compose -f docker-compose.prod.yml ps

echo ""
echo "========================================="
echo "✓ 部署完成！"
echo "========================================="
echo ""
echo "服務地址："
echo "  - 使用者介面: http://app.172-237-11-179.sslip.io"
echo "  - 系統方介面: http://admin.172-237-11-179.sslip.io"
echo "  - API 文件: http://api.172-237-11-179.sslip.io/docs"
echo ""
'@

# 5. 執行遠端部署
Write-Step "執行遠端部署..."
Write-Host ""

# 確定部署模式
$DeployMode = "normal"
if ($RestartOnly) {
    $DeployMode = "restart-only"
    Write-Host "模式: 僅重啟服務" -ForegroundColor Yellow
} elseif ($FullDeploy) {
    $DeployMode = "full"
    Write-Host "模式: 完整部署（重建容器）" -ForegroundColor Yellow
} else {
    Write-Host "模式: 標準部署（增量更新）" -ForegroundColor Yellow
}
Write-Host ""

# 將部署腳本上傳並執行
$TempScriptPath = "/tmp/deploy_aihr_$(Get-Date -Format 'yyyyMMddHHmmss').sh"

# 上傳腳本
$DeployScript | ssh -i $SSHKeyPath "$Username@$ServerIP" "cat > $TempScriptPath && chmod +x $TempScriptPath"

if ($LASTEXITCODE -ne 0) {
    Write-Error-Custom "部署腳本上傳失敗"
    exit 1
}

# 執行部署腳本
ssh -i $SSHKeyPath "$Username@$ServerIP" "bash $TempScriptPath $DeployMode"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=========================================" -ForegroundColor Green
    Write-Host "✓✓✓ 部署成功！✓✓✓" -ForegroundColor Green
    Write-Host "=========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "接下來你可以：" -ForegroundColor Cyan
    Write-Host "  1. 瀏覽器測試各個介面"
    Write-Host "  2. 查看日誌: ssh aihr-linode 'cd /opt/aihr && docker compose -f docker-compose.prod.yml logs -f'" -ForegroundColor White
    Write-Host "  3. 執行驗證: ssh aihr-linode 'cd /opt/aihr && bash scripts/verify_deployment.sh'" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host ""
    Write-Error-Custom "部署失敗"
    Write-Host "請檢查日誌："
    Write-Host "  ssh aihr-linode 'cd /opt/aihr && docker compose -f docker-compose.prod.yml logs'" -ForegroundColor Yellow
    exit 1
}

# 清理臨時腳本
ssh -i $SSHKeyPath "$Username@$ServerIP" "rm -f $TempScriptPath" 2>&1 | Out-Null

Write-Host "本地時間: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkGray
