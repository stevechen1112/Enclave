# Linode 部署指南（無網域 / sslip.io 方案）

## 伺服器資訊
- **主機**: Linode
- **IP**: 172.237.11.179
- **SSH**: `ssh root@172.237.11.179`

## 網域方案：sslip.io

由於目前沒有正式網域，我們使用 **sslip.io** 服務來獲得可用的 hostname，實現「網域分流」效果：

### 使用的網域
- **使用者介面（租戶）**: `https://app.172-237-11-179.sslip.io`
- **系統方介面（Admin）**: `https://admin.172-237-11-179.sslip.io`
- **後端 API**: `https://api.172-237-11-179.sslip.io`
- **Admin API**: `https://admin-api.172-237-11-179.sslip.io`
- **監控（Grafana）**: `https://grafana.172-237-11-179.sslip.io`
- **租戶子網域**: `https://<tenant>.172-237-11-179.sslip.io`

### sslip.io 原理
- `app.172-237-11-179.sslip.io` 會自動解析到 `172.237.11.179`
- 無需註冊或設定 DNS，立即可用
- 支援 Let's Encrypt SSL 憑證
- **適合 PoC、測試、臨時上線；有正式網域後再切換**

---

## 部署步驟

### 1. 準備 Linode VM

#### 1.1 建議規格
至少選擇：
- **Linode 4GB**: 2 CPU / 4GB RAM / 80GB Storage
- 作業系統：Ubuntu 22.04 LTS 或 24.04 LTS

#### 1.2 初始化伺服器
```bash
# SSH 登入
ssh root@172.237.11.179

# 更新系統
apt update && apt upgrade -y

# 安裝必要工具
apt install -y curl git vim ufw

# 設定時區
timedatectl set-timezone Asia/Taipei
```

### 2. 安裝 Docker & Docker Compose

```bash
# 安裝 Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# 啟用 Docker 服務
systemctl enable docker
systemctl start docker

# 驗證 Docker 版本
docker --version

# Docker Compose 已內建在 Docker CLI（docker compose 指令）
docker compose version
```

### 3. 設定防火牆

```bash
# 允許 SSH, HTTP, HTTPS
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp

# 啟用防火牆（確認 SSH 已允許後再啟用）
ufw --force enable

# 檢查狀態
ufw status
```

### 4. 部署專案

#### 4.1 Clone 專案
```bash
cd /opt
git clone https://github.com/stevechen1112/aihr.git
cd aihr
```

#### 4.2 生成生產環境配置
```bash
# 生成隨機密鑰與密碼
python3 scripts/generate_secrets.py --output .env.production

# 編輯 .env.production，填入必填項目
vim .env.production
```

#### 4.3 必填環境變數
編輯 `.env.production`，至少填入以下項目：

```bash
# === 核心配置 ===
APP_ENV=production
SECRET_KEY=<generate_secrets.py 已生成>

# === 網域配置（sslip.io）===
BACKEND_CORS_ORIGINS=https://app.172-237-11-179.sslip.io,https://admin.172-237-11-179.sslip.io
FRONTEND_URL=https://app.172-237-11-179.sslip.io
ADMIN_FRONTEND_URL=https://admin.172-237-11-179.sslip.io

# === 資料庫 ===
POSTGRES_SERVER=postgres
POSTGRES_USER=unihr
POSTGRES_PASSWORD=<generate_secrets.py 已生成>
POSTGRES_DB=unihr

# === Redis ===
REDIS_HOST=redis
REDIS_PASSWORD=<generate_secrets.py 已生成>
ADMIN_REDIS_PASSWORD=<generate_secrets.py 已生成>

# === AI API Keys（必須填寫真實 key）===
OPENAI_API_KEY=sk-proj-...
VOYAGE_API_KEY=pa-...

# === LlamaParse ===
LLAMA_CLOUD_API_KEY=llx-...

# === 初始超級管理員 ===
FIRST_SUPERUSER_EMAIL=admin@yourdomain.com
FIRST_SUPERUSER_PASSWORD=<強隨機密碼>

# === Grafana ===
GRAFANA_PASSWORD=<generate_secrets.py 已生成>
```

### 5. 啟動服務

```bash
# 啟動所有服務（後台運行）
docker compose -f docker-compose.prod.yml --env-file .env.production up -d

# 查看服務狀態
docker compose -f docker-compose.prod.yml ps

# 查看日誌（可選）
docker compose -f docker-compose.prod.yml logs -f web
```

### 6. 初始化資料庫

```bash
# 執行資料庫遷移
docker compose -f docker-compose.prod.yml exec web alembic upgrade head

# 創建初始租戶與超級管理員
docker compose -f docker-compose.prod.yml exec web python scripts/initial_data.py
```

### 7. 設定 SSL 憑證（Let's Encrypt）

#### 7.1 安裝 Certbot
```bash
apt install -y certbot python3-certbot-nginx
```

#### 7.2 停用 Gateway 以便取得憑證（HTTP-01 挑戰）
```bash
docker compose -f docker-compose.prod.yml stop gateway
```

#### 7.3 取得憑證（多網域一次申請）
```bash
certbot certonly --standalone \
  -d app.172-237-11-179.sslip.io \
  -d admin.172-237-11-179.sslip.io \
  -d api.172-237-11-179.sslip.io \
  -d admin-api.172-237-11-179.sslip.io \
  -d grafana.172-237-11-179.sslip.io \
  --email your-email@example.com \
  --agree-tos \
  --non-interactive
```

憑證會存放在：
- `/etc/letsencrypt/live/app.172-237-11-179.sslip.io/fullchain.pem`
- `/etc/letsencrypt/live/app.172-237-11-179.sslip.io/privkey.pem`

#### 7.4 更新 gateway.conf 使用 SSL
編輯 `nginx/gateway.conf`，在每個 `server` block 中加入：

```nginx
listen 443 ssl http2;
ssl_certificate /etc/letsencrypt/live/app.172-237-11-179.sslip.io/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/app.172-237-11-179.sslip.io/privkey.pem;

# SSL 優化
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers HIGH:!aNULL:!MD5;
ssl_prefer_server_ciphers on;
```

#### 7.5 掛載憑證到 Gateway 容器
編輯 `docker-compose.prod.yml`，在 `gateway` 服務中加入：

```yaml
gateway:
  volumes:
    - ./nginx/gateway.conf:/etc/nginx/conf.d/default.conf:ro
    - /etc/letsencrypt:/etc/letsencrypt:ro  # 掛載憑證目錄
```

#### 7.6 重啟 Gateway
```bash
docker compose -f docker-compose.prod.yml up -d gateway
```

#### 7.7 設定自動續期
```bash
# 測試續期
certbot renew --dry-run

# 加入 cron（每天凌晨 3 點檢查）
echo "0 3 * * * certbot renew --quiet && docker compose -f /opt/aihr/docker-compose.prod.yml restart gateway" | crontab -
```

---

## 驗證部署

### 1. 檢查服務健康狀態
```bash
docker compose -f docker-compose.prod.yml ps
```
所有服務應顯示 `Up (healthy)`。

### 2. 測試各個介面

```bash
# API 健康檢查
curl https://api.172-237-11-179.sslip.io/health

# 使用者介面
curl -I https://app.172-237-11-179.sslip.io

# 系統方介面
curl -I https://admin.172-237-11-179.sslip.io

# Grafana
curl -I https://grafana.172-237-11-179.sslip.io
```

### 3. 瀏覽器測試
- **使用者介面**: https://app.172-237-11-179.sslip.io
- **系統方介面**: https://admin.172-237-11-179.sslip.io
- **Grafana**: https://grafana.172-237-11-179.sslip.io
  - 預設帳號: `admin`
  - 密碼: `.env.production` 中的 `GRAFANA_PASSWORD`

---

## 日常維運

### 查看日誌
```bash
# 所有服務
docker compose -f docker-compose.prod.yml logs -f

# 特定服務
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs -f worker
docker compose -f docker-compose.prod.yml logs -f gateway
```

### 重啟服務
```bash
# 重啟特定服務
docker compose -f docker-compose.prod.yml restart web

# 重啟所有服務
docker compose -f docker-compose.prod.yml restart
```

### 更新程式碼
```bash
cd /opt/aihr
git pull
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml exec web alembic upgrade head
```

### 備份資料庫
```bash
# 手動備份
bash scripts/backup.sh

# 設定每日自動備份（凌晨 2 點）
echo "0 2 * * * cd /opt/aihr && bash scripts/backup.sh" | crontab -e
```

---

## 切換到正式網域

當你準備好正式網域（例如 `yourdomain.com`）時：

### 1. DNS 設定
在你的 DNS 服務商設定：
```
A     app.yourdomain.com       -> 172.237.11.179
A     admin.yourdomain.com     -> 172.237.11.179
A     api.yourdomain.com       -> 172.237.11.179
A     admin-api.yourdomain.com -> 172.237.11.179
A     grafana.yourdomain.com   -> 172.237.11.179
A     *.yourdomain.com         -> 172.237.11.179  # wildcard for tenants
```

### 2. 更新環境變數
編輯 `.env.production`，將所有 `172-237-11-179.sslip.io` 改為 `yourdomain.com`。

### 3. 重新申請 SSL
```bash
certbot certonly --standalone \
  -d app.yourdomain.com \
  -d admin.yourdomain.com \
  -d api.yourdomain.com \
  -d admin-api.yourdomain.com \
  -d grafana.yourdomain.com \
  --email your-email@example.com \
  --agree-tos
```

### 4. 更新 Nginx 配置
編輯 `nginx/gateway.conf`，將所有 `server_name` 從 `*.172-237-11-179.sslip.io` 改為 `*.yourdomain.com`。

### 5. 重啟服務
```bash
docker compose -f docker-compose.prod.yml restart gateway
docker compose -f docker-compose.prod.yml restart web
```

---

## 故障排除

### 問題 1: 無法存取服務
```bash
# 檢查防火牆
ufw status

# 檢查 Docker 服務
docker compose -f docker-compose.prod.yml ps

# 檢查 Gateway 日誌
docker compose -f docker-compose.prod.yml logs gateway
```

### 問題 2: SSL 憑證取得失敗
- 確認 80 port 未被佔用（Gateway 需暫停）
- 確認 DNS 已正確解析（`dig app.172-237-11-179.sslip.io` 應回傳 `172.237.11.179`）
- 檢查防火牆是否允許 80 port

### 問題 3: 資料庫連線錯誤
```bash
# 檢查 PostgreSQL 是否正常
docker compose -f docker-compose.prod.yml exec postgres pg_isready

# 檢查密碼是否正確
grep POSTGRES_PASSWORD .env.production
```

### 問題 4: Worker 任務不執行
```bash
# 檢查 Redis 連線
docker compose -f docker-compose.prod.yml exec redis redis-cli -a <REDIS_PASSWORD> ping

# 檢查 Worker 日誌
docker compose -f docker-compose.prod.yml logs worker

# 重啟 Worker
docker compose -f docker-compose.prod.yml restart worker
```

---

## 效能調校（可選）

### Linode 建議規格演進
- **測試/小規模**: Linode 4GB (2 CPU / 4GB RAM)
- **中等規模**: Linode 8GB (4 CPU / 8GB RAM)
- **大規模**: Linode 16GB (6 CPU / 16GB RAM) + 分離資料庫

### 考慮使用 Linode 託管服務
- **資料庫**: Linode Managed Database (PostgreSQL)
- **物件儲存**: Linode Object Storage（替代本地 uploads volume）
- **負載平衡**: Linode NodeBalancer（高可用架構）

---

## 安全建議

1. **限制 SSH 存取**
   ```bash
   # 只允許特定 IP SSH（例如辦公室 IP）
   ufw delete allow 22/tcp
   ufw allow from <YOUR_IP> to any port 22
   ```

2. **定期更新系統**
   ```bash
   apt update && apt upgrade -y
   ```

3. **監控異常存取**
   - Grafana 查看 Nginx access logs
   - 定期檢查 `docker compose logs`

4. **資料庫備份異地存放**
   - 將備份上傳至 Linode Object Storage 或其他雲端儲存

---

## 聯絡與支援
- GitHub: https://github.com/stevechen1112/aihr
- Issues: 在 GitHub 提交問題或功能建議
