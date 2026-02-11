# ========================================================
# SSH Key Setup Script (Windows PowerShell)
# ========================================================

param(
    [string]$ServerIP = '172.237.11.179',
    [string]$Username = 'root'
)

$SSHKeyPath = "$env:USERPROFILE\.ssh\id_rsa_linode"
$SSHPubKeyPath = "$SSHKeyPath.pub"

Write-Host '==========================================' -ForegroundColor Cyan
Write-Host 'SSH Key Auto Setup Tool' -ForegroundColor Cyan
Write-Host '==========================================' -ForegroundColor Cyan
Write-Host ''

# 1. Check SSH directory
if (-not (Test-Path "$env:USERPROFILE\.ssh")) {
    Write-Host '[1/5] Creating .ssh directory...' -ForegroundColor Yellow
    New-Item -ItemType Directory -Path "$env:USERPROFILE\.ssh" | Out-Null
    Write-Host 'OK .ssh directory created' -ForegroundColor Green
} else {
    Write-Host '[1/5] .ssh directory exists' -ForegroundColor Green
}

# 2. Generate SSH key pair
if (-not (Test-Path $SSHKeyPath)) {
    Write-Host '[2/5] Generating SSH key pair...' -ForegroundColor Yellow
    ssh-keygen -t rsa -b 4096 -f $SSHKeyPath -N '' -C 'aihr-deployment'
    Write-Host 'OK SSH key generated' -ForegroundColor Green
} else {
    Write-Host '[2/5] SSH key already exists' -ForegroundColor Green
}

# 3. Read public key
Write-Host '[3/5] Reading public key...' -ForegroundColor Yellow
$PublicKey = Get-Content $SSHPubKeyPath -Raw
Write-Host 'OK Public key read' -ForegroundColor Green

# 4. Upload public key to server
Write-Host '[4/5] Uploading public key to server...' -ForegroundColor Yellow
Write-Host "Connecting to: $Username@$ServerIP" -ForegroundColor Cyan
Write-Host 'Please enter server password (ONLY THIS ONCE):' -ForegroundColor Yellow
Write-Host ''

$Command = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$PublicKey' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo 'Public key added successfully'"

ssh "$Username@$ServerIP" $Command

if ($LASTEXITCODE -eq 0) {
    Write-Host 'OK Public key uploaded' -ForegroundColor Green
} else {
    Write-Host 'ERROR Public key upload failed' -ForegroundColor Red
    exit 1
}

# 5. Configure SSH config
Write-Host '[5/5] Configuring SSH config...' -ForegroundColor Yellow
$SSHConfigPath = "$env:USERPROFILE\.ssh\config"
$ConfigEntry = @'

# UniHR Linode Server
Host aihr-linode
    HostName 172.237.11.179
    User root
    IdentityFile ~/.ssh/id_rsa_linode
    StrictHostKeyChecking no
'@

if (Test-Path $SSHConfigPath) {
    $ConfigContent = Get-Content $SSHConfigPath -Raw
    if ($ConfigContent -notmatch 'Host aihr-linode') {
        Add-Content -Path $SSHConfigPath -Value $ConfigEntry
        Write-Host 'OK SSH config updated' -ForegroundColor Green
    } else {
        Write-Host 'OK SSH config already exists' -ForegroundColor Green
    }
} else {
    Set-Content -Path $SSHConfigPath -Value $ConfigEntry.TrimStart()
    Write-Host 'OK SSH config created' -ForegroundColor Green
}

# 6. Test connection
Write-Host ''
Write-Host '==========================================' -ForegroundColor Cyan
Write-Host 'OK Setup complete!' -ForegroundColor Green
Write-Host '==========================================' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Testing passwordless login...' -ForegroundColor Yellow
Write-Host ''

ssh -i $SSHKeyPath "$Username@$ServerIP" "echo 'Connection successful!'; uname -a"

if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host '==========================================' -ForegroundColor Green
    Write-Host 'SUCCESS SSH passwordless login configured!' -ForegroundColor Green
    Write-Host '==========================================' -ForegroundColor Green
    Write-Host ''
    Write-Host 'You can now login without password:' -ForegroundColor Cyan
    Write-Host '  Method 1: ssh aihr-linode' -ForegroundColor White
    Write-Host "  Method 2: ssh -i $SSHKeyPath $Username@$ServerIP" -ForegroundColor White
    Write-Host ''
    Write-Host 'One-click deployment:' -ForegroundColor Cyan
    Write-Host '  .\scripts\deploy_remote.ps1' -ForegroundColor White
    Write-Host ''
} else {
    Write-Host ''
    Write-Host 'ERROR Connection test failed' -ForegroundColor Red
    exit 1
}
