#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Upload SSH public key to remote server with automatic password input
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ServerIP,
    
    [Parameter(Mandatory=$true)]
    [string]$Password,
    
    [Parameter(Mandatory=$false)]
    [string]$PublicKeyPath = "$env:USERPROFILE\.ssh\id_rsa_linode.pub"
)

Write-Host "⚙️  Uploading SSH key to $ServerIP..." -ForegroundColor Cyan

# Read public key
if (-not (Test-Path $PublicKeyPath)) {
    Write-Host "❌ Public key not found: $PublicKeyPath" -ForegroundColor Red
    exit 1
}

$pubKey = Get-Content $PublicKeyPath

# Create temporary expect-like script using PowerShell
$tempScript = @"
`$pubKey = @'
$pubKey
'@

# Upload key using here-string to avoid password prompt issues
`$escapedKey = `$pubKey -replace "'", "'\\\''"
ssh root@$ServerIP "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '`$escapedKey' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo 'Key uploaded successfully'"
"@

Write-Host "📤 Attempting key upload..." -ForegroundColor Yellow

# Method 1: Try direct upload with public key echoed via stdin
$command = "ssh root@$ServerIP `"mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo 'SSH key uploaded'`""

try {
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo.FileName = "ssh"
    $proc.StartInfo.Arguments = "root@$ServerIP `"mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys`""
    $proc.StartInfo.UseShellExecute = $false
    $proc.StartInfo.RedirectStandardInput = $true
    $proc.StartInfo.RedirectStandardOutput = $true
    $proc.StartInfo.RedirectStandardError = $true
    
    $proc.Start() | Out-Null
    
    # Write password then public key
    $proc.StandardInput.WriteLine($Password)
    Start-Sleep -Milliseconds 500
    $proc.StandardInput.WriteLine($pubKey)
    $proc.StandardInput.Close()
    
    $proc.WaitForExit(10000)
    
    $output = $proc.StandardOutput.ReadToEnd()
    $error = $proc.StandardError.ReadToEnd()
    
    if ($proc.ExitCode -eq 0) {
        Write-Host "✅ SSH key uploaded successfully!" -ForegroundColor Green
        Write-Host "🔑 Testing passwordless login..." -ForegroundColor Cyan
        
        # Test connection
        $testResult = ssh -o BatchMode=yes -o ConnectTimeout=5 root@$ServerIP "echo 'Passwordless login works!'" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ $testResult" -ForegroundColor Green
            return 0
        }
    }
    
    throw "Upload failed: $error"
    
} catch {
    Write-Host "⚠️  Method 1 failed, trying alternative..." -ForegroundColor Yellow
    
    # Method 2: Manual command construction
    Write-Host "Please enter password '$Password' when prompted..." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Executing: ssh root@$ServerIP '...'" -ForegroundColor Gray
    
    # This will require manual password input
    $result = ssh root@$ServerIP "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$pubKey' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo 'SSH key uploaded'"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ SSH key uploaded!" -ForegroundColor Green
        return 0
    } else {
        Write-Host "❌ Failed to upload SSH key" -ForegroundColor Red
        return 1
    }
}
