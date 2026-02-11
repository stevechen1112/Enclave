# 🚀 Linode 自動部署 — 快速開始

> **目標**：從本地 Windows 一鍵部署到 Linode 伺服器，無需每次輸入密碼

---

## ⚡ 三步驟開始

### 第 1 步：設定 SSH 免密碼登入（僅需一次）

```powershell
# 在本地 PowerShell 執行
cd C:\Users\User\Desktop\aihr
.\scripts\setup_ssh_key.ps1
```

**會提示輸入伺服器密碼（僅此一次）**

完成後會顯示：
```
✓✓✓ SSH 免密碼登入設定成功！✓✓✓

現在你可以使用以下方式登入（無需密碼）：
  方式 1: ssh aihr-linode
  方式 2: ssh -i ~/.ssh/id_rsa_linode root@172.237.11.179
```

---

### 第 2 步：初始部署到伺服器（首次需要）

```powershell
# 免密碼登入伺服器
ssh aihr-linode

# 執行初始部署腳本
cd /opt
git clone https://github.com/stevechen1112/aihr.git
cd aihr
bash scripts/deploy_linode.sh
```

**腳本會自動：**
1. ✅ 檢查 Docker / Git / Python
2. ✅ 生成環境配置（.env.production）
3. ✅ **暫停並提示你填入 API keys**
4. ✅ 配置 sslip.io 網域
5. ✅ 啟動所有 Docker 服務
6. ✅ 初始化資料庫

**需要手動填入的項目**（腳本會暫停提示）：
```bash
vim .env.production

# 必填：
OPENAI_API_KEY=sk-proj-...
VOYAGE_API_KEY=pa-...
LLAMAPARSE_API_KEY=llx-...
FIRST_SUPERUSER_EMAIL=admin@yourdomain.com
FIRST_SUPERUSER_PASSWORD=<強隨機密碼>
```

填寫完按 `:wq` 儲存退出，腳本會繼續。

---

### 第 3 步：之後的更新（本地一鍵）

```powershell
# 在本地 PowerShell 執行，全自動部署！
cd C:\Users\User\Desktop\aihr
.\scripts\deploy_remote.ps1
```

**腳本會自動執行：**
1. ✅ 檢查本地 Git 更改
2. ✅ 提示你提交並推送到 GitHub（可選）
3. ✅ SSH 連線到伺服器（**免密碼**！）
4. ✅ 拉取最新代碼
5. ✅ 更新 Docker 容器
6. ✅ 執行資料庫遷移
7. ✅ 顯示服務狀態

**完成顯示：**
```
=========================================
✓✓✓ 部署成功！✓✓✓
=========================================

服務地址：
  - 使用者介面: http://app.172-237-11-179.sslip.io
  - 系統方介面: http://admin.172-237-11-179.sslip.io
  - API 文件: http://api.172-237-11-179.sslip.io/docs
```

---

## 🎯 存取網址（sslip.io 臨時網域）

| 服務 | 網址 |
|-----|-----|
| 使用者介面 | http://app.172-237-11-179.sslip.io |
| 系統方介面 | http://admin.172-237-11-179.sslip.io |
| API 文件 | http://api.172-237-11-179.sslip.io/docs |
| Grafana 監控 | http://grafana.172-237-11-179.sslip.io |

**登入資訊：**
- 超級管理員：`.env.production` 中的 `FIRST_SUPERUSER_EMAIL/PASSWORD`
- Grafana：帳號 `admin`，密碼見 `.env.production` 的 `GRAFANA_PASSWORD`

---

## 🛠️ 進階用法

### 部署選項

```powershell
# 標準部署（增量更新）
.\scripts\deploy_remote.ps1

# 跳過 Git push（已手動推送時）
.\scripts\deploy_remote.ps1 -SkipGitPush

# 僅重啟服務（不更新代碼）
.\scripts\deploy_remote.ps1 -RestartOnly

# 完整重建（清除並重建所有容器）
.\scripts\deploy_remote.ps1 -FullDeploy
```

### 遠端管理指令

```powershell
# 查看日誌
ssh aihr-linode "cd /opt/aihr && docker compose -f docker-compose.prod.yml logs -f web"

# 檢查服務狀態
ssh aihr-linode "cd /opt/aihr && docker compose -f docker-compose.prod.yml ps"

# 執行驗證腳本
ssh aihr-linode "cd /opt/aihr && bash scripts/verify_deployment.sh"

# 重啟特定服務
ssh aihr-linode "cd /opt/aihr && docker compose -f docker-compose.prod.yml restart web"
```

### 快速登入

```powershell
# 免密碼登入伺服器
ssh aihr-linode

# 或完整路徑
ssh -i ~/.ssh/id_rsa_linode root@172.237.11.179
```

---

## 📋 完整工作流程

```
┌─────────────┐
│  本地開發   │ 修改代碼、測試
└──────┬──────┘
       │
       ▼
┌─────────────────────────┐
│ .\scripts\deploy_remote.ps1 │ ← 一鍵執行！
└──────┬──────────────────┘
       │
       ├─→ [檢查 Git 更改]
       ├─→ [Commit + Push 到 GitHub]
       ├─→ [SSH 連線到 Linode（免密碼）]
       ├─→ [Git pull 最新代碼]
       ├─→ [Docker 更新容器]
       ├─→ [資料庫遷移]
       └─→ [驗證服務狀態]
       
       ▼
┌─────────────┐
│  部署完成   │ ✓ 自動更新上線
└─────────────┘
```

---

## 🔐 安全說明

1. **SSH 私鑰位置**：`~/.ssh/id_rsa_linode`
   - 不會被 commit 到 Git
   - 請妥善保管

2. **敏感資料保護**：
   - `.env.production` 僅存在於伺服器上
   - `.gitignore` 已排除所有 `.env*` 檔案

3. **GitHub 權限**：
   - 確保你有 push 權限到 `stevechen1112/aihr`
   - 建議使用 Personal Access Token

---

## 🆘 故障排除

### SSH 連線失敗
```powershell
# 重新設定 SSH
.\scripts\setup_ssh_key.ps1

# 測試連線
ssh -v aihr-linode
```

### 部署失敗
```powershell
# 查看遠端日誌
ssh aihr-linode "cd /opt/aihr && docker compose -f docker-compose.prod.yml logs --tail=50"

# 手動登入除錯
ssh aihr-linode
cd /opt/aihr
docker compose -f docker-compose.prod.yml ps
```

### Git push 失敗
```powershell
# 檢查 GitHub 認證
git remote -v
git config user.email
git config user.name

# 手動推送
git push origin main
```

---

## 📚 完整文件

- **[SSH 自動部署指南](./SSH_AUTO_DEPLOY.md)** - 詳細設定與工作流程
- **[Linode 部署指南](./LINODE_DEPLOYMENT.md)** - sslip.io + SSL + 切換正式網域
- **[快速參考](./LINODE_QUICKSTART.md)** - 所有常用命令

---

## 📞 需要協助？

- GitHub: https://github.com/stevechen1112/aihr
- Issues: https://github.com/stevechen1112/aihr/issues

---

**就是這麼簡單！一次設定，永久自動部署 🚀**
