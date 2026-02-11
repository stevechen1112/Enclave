# ========================================================
# SSH 密鑰設定腳本 (Windows PowerShell)
# ========================================================
# 用途：為 Linode 伺服器設定免密碼 SSH 登入
# 使用：只需執行一次，輸入密碼後即可永久免密碼登入
# ========================================================

param(
    [string]$ServerIP = "172.237.11.179",
    [string]$Username = "root"
)

$SSHKeyPath = "$env:USERPROFILE\.ssh\id_rsa_linode"
$SSHPubKeyPath = "$SSHKeyPath.pub"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "SSH 密鑰自動設定工具" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 檢查 SSH 目錄
if (-not (Test-Path "$env:USERPROFILE\.ssh")) {
    Write-Host "[1/5] 創建 .ssh 目錄..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path "$env:USERPROFILE\.ssh" | Out-Null
    Write-Host "✓ .ssh 目錄已創建" -ForegroundColor Green
} else {
    Write-Host "[1/5] .ssh 目錄已存在" -ForegroundColor Green
}

# 2. 生成 SSH 密鑰對（如果不存在）
if (-not (Test-Path $SSHKeyPath)) {
    Write-Host "[2/5] 生成 SSH 密鑰對..." -ForegroundColor Yellow
    ssh-keygen -t rsa -b 4096 -f $SSHKeyPath -N '""' -C "aihr-deployment"
    Write-Host "✓ SSH 密鑰已生成: $SSHKeyPath" -ForegroundColor Green
} else {
    Write-Host "[2/5] SSH 密鑰已存在，跳過生成" -ForegroundColor Green
}

# 3. 讀取公鑰內容
Write-Host "[3/5] 讀取公鑰..." -ForegroundColor Yellow
$PublicKey = Get-Content $SSHPubKeyPath -Raw
Write-Host "✓ 公鑰已讀取" -ForegroundColor Green

# 4. 上傳公鑰到伺服器（需要輸入密碼）
Write-Host "[4/5] 上傳公鑰到伺服器..." -ForegroundColor Yellow
Write-Host "即將連線到: $Username@$ServerIP" -ForegroundColor Cyan
Write-Host "請輸入伺服器密碼（僅此一次）：" -ForegroundColor Yellow
Write-Host ""

# 使用 ssh 命令將公鑰加入到 authorized_keys
$Command = @"
mkdir -p ~/.ssh && \
chmod 700 ~/.ssh && \
echo '$PublicKey' >> ~/.ssh/authorized_keys && \
chmod 600 ~/.ssh/authorized_keys && \
echo 'Public key added successfully'
"@

ssh "$Username@$ServerIP" $Command

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ 公鑰已成功上傳" -ForegroundColor Green
} else {
    Write-Host "✗ 公鑰上傳失敗" -ForegroundColor Red
    exit 1
}

# 5. 配置 SSH config 文件
Write-Host "[5/5] 配置 SSH config..." -ForegroundColor Yellow
$SSHConfigPath = "$env:USERPROFILE\.ssh\config"
$ConfigEntry = @"

# UniHR Linode Server
Host aihr-linode
    HostName $ServerIP
    User $Username
    IdentityFile $SSHKeyPath
    StrictHostKeyChecking no
"@

# 檢查是否已存在配置
if (Test-Path $SSHConfigPath) {
    $ConfigContent = Get-Content $SSHConfigPath -Raw
    if ($ConfigContent -notmatch 'Host aihr-linode') {
        Add-Content -Path $SSHConfigPath -Value $ConfigEntry
        Write-Host "✓ SSH config 已更新" -ForegroundColor Green
    } else {
        Write-Host "✓ SSH config 已存在，跳過" -ForegroundColor Green
    }
} else {
    Set-Content -Path $SSHConfigPath -Value $ConfigEntry.TrimStart()
    Write-Host "✓ SSH config 已創建" -ForegroundColor Green
}

# 6. 測試連線
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "✓ 設定完成！" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "測試免密碼登入..." -ForegroundColor Yellow
Write-Host ""

ssh -i $SSHKeyPath "$Username@$ServerIP" "echo '連線成功！'; uname -a"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=========================================" -ForegroundColor Green
    Write-Host "✓✓✓ SSH 免密碼登入設定成功！✓✓✓" -ForegroundColor Green
    Write-Host "=========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "現在你可以使用以下方式登入（無需密碼）：" -ForegroundColor Cyan
    Write-Host "  方式 1: ssh aihr-linode" -ForegroundColor White
    Write-Host "  方式 2: ssh -i $SSHKeyPath $Username@$ServerIP" -ForegroundColor White
    Write-Host ""
    Write-Host "一鍵部署指令：" -ForegroundColor Cyan
    Write-Host "  .\scripts\deploy_remote.ps1" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "✗ 連線測試失敗，請檢查設定" -ForegroundColor Red
    exit 1
}
