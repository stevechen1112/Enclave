# Linode 快速部署 — 命令集

## 伺服器資訊
- IP: `172.237.11.179`
- SSH: `ssh root@172.237.11.179`
- 網域: 使用 `sslip.io` (例: `app.172-237-11-179.sslip.io`)

---

## 一鍵部署（推薦）

```bash
# SSH 登入 Linode
ssh root@172.237.11.179

# 執行部署腳本
cd /opt
git clone https://github.com/stevechen1112/aihr.git
cd aihr
bash scripts/deploy_linode.sh
```

腳本會自動：
1. ✓ 檢查必要工具（Docker, Git, Python）
2. ✓ Clone/更新專案
3. ✓ 生成環境配置（.env.production）
4. ✓ 配置 sslip.io 網域
5. ✓ 啟動 Docker 服務
6. ✓ 初始化資料庫

**需要手動填入的項目**：
- `OPENAI_API_KEY`
- `VOYAGE_API_KEY`
- `LLAMAPARSE_API_KEY`
- `FIRST_SUPERUSER_EMAIL`
- `FIRST_SUPERUSER_PASSWORD`

---

## 驗證部署

```bash
# 執行驗證腳本
bash scripts/verify_deployment.sh
```

驗證項目：
- Docker 服務狀態
- API 健康檢查
- 前端介面存取
- DNS 解析
- 資料庫連線

---

## 存取網址（初次部署 HTTP）

| 服務 | 網址 |
|-----|-----|
| 使用者介面 | http://app.172-237-11-179.sslip.io |
| 系統方介面 | http://admin.172-237-11-179.sslip.io |
| API 文件 | http://api.172-237-11-179.sslip.io/docs |
| Grafana | http://grafana.172-237-11-179.sslip.io |

---

## 手動部署步驟（詳細版）

### 1. 伺服器初始化

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

### 2. 安裝 Docker

```bash
# 安裝 Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# 啟用服務
systemctl enable docker
systemctl start docker

# 驗證
docker --version
docker compose version
```

### 3. 設定防火牆

```bash
# 允許必要端口
ufw allow 22/tcp   # SSH
ufw allow 80/tcp   # HTTP
ufw allow 443/tcp  # HTTPS

# 啟用防火牆
ufw --force enable

# 檢查狀態
ufw status
```

### 4. Clone 專案

```bash
cd /opt
git clone https://github.com/stevechen1112/aihr.git
cd aihr
```

### 5. 生成環境配置

```bash
# 生成密鑰與密碼
python3 scripts/generate_secrets.py --output .env.production

# 編輯配置檔
vim .env.production
```

**必填項目**：
```bash
# API Keys
OPENAI_API_KEY=sk-proj-...
VOYAGE_API_KEY=pa-...
LLAMAPARSE_API_KEY=llx-...

# 超級管理員
FIRST_SUPERUSER_EMAIL=admin@yourdomain.com
FIRST_SUPERUSER_PASSWORD=<強隨機密碼>

# 網域配置（sslip.io）
BACKEND_CORS_ORIGINS=http://app.172-237-11-179.sslip.io,http://admin.172-237-11-179.sslip.io
FRONTEND_URL=http://app.172-237-11-179.sslip.io
ADMIN_FRONTEND_URL=http://admin.172-237-11-179.sslip.io
```

### 6. 配置 Gateway (使用 sslip.io)

```bash
# 使用 sslip.io 版本的 gateway 配置
cp nginx/gateway.conf.sslip nginx/gateway.conf

# 或者直接在 docker-compose.prod.yml 中修改 volumes:
# - ./nginx/gateway.conf.sslip:/etc/nginx/conf.d/default.conf:ro
```

### 7. 啟動服務

```bash
# 啟動所有服務
docker compose -f docker-compose.prod.yml --env-file .env.production up -d

# 查看狀態
docker compose -f docker-compose.prod.yml ps

# 查看日誌
docker compose -f docker-compose.prod.yml logs -f
```

### 8. 初始化資料庫

```bash
# 執行資料庫遷移
docker compose -f docker-compose.prod.yml exec web alembic upgrade head

# 創建初始租戶與超級管理員
docker compose -f docker-compose.prod.yml exec web python scripts/initial_data.py
```

---

## 配置 SSL（讓 HTTP 變成 HTTPS）

### 1. 停止 Gateway（讓 Certbot 使用 80 port）

```bash
docker compose -f docker-compose.prod.yml stop gateway
```

### 2. 安裝 Certbot

```bash
apt install -y certbot python3-certbot-nginx
```

### 3. 取得憑證（一次申請多個網域）

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

憑證位置：
- `/etc/letsencrypt/live/app.172-237-11-179.sslip.io/fullchain.pem`
- `/etc/letsencrypt/live/app.172-237-11-179.sslip.io/privkey.pem`

### 4. 啟用 HTTPS（編輯 gateway.conf）

編輯 `nginx/gateway.conf.sslip`，取消所有 SSL 相關註解：

```nginx
# 將所有 server 的 listen 改為：
listen 443 ssl http2;
ssl_certificate     /etc/letsencrypt/live/app.172-237-11-179.sslip.io/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/app.172-237-11-179.sslip.io/privkey.pem;
ssl_protocols       TLSv1.2 TLSv1.3;
ssl_ciphers         HIGH:!aNULL:!MD5;
ssl_prefer_server_ciphers on;

# 啟用底部的 HTTP → HTTPS redirect
```

### 5. 重啟 Gateway

```bash
docker compose -f docker-compose.prod.yml up -d gateway
```

### 6. 設定自動續期

```bash
# 測試續期
certbot renew --dry-run

# 加入 cron（每天凌晨 3 點檢查）
echo "0 3 * * * certbot renew --quiet && docker compose -f /opt/aihr/docker-compose.prod.yml restart gateway" | crontab -
```

---

## 常用指令

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

### 檢查服務健康狀態
```bash
# Docker 服務
docker compose -f docker-compose.prod.yml ps

# PostgreSQL
docker compose -f docker-compose.prod.yml exec postgres pg_isready

# Redis
docker compose -f docker-compose.prod.yml exec redis redis-cli -a <REDIS_PASSWORD> ping
```

---

## 切換到正式網域

當準備好正式網域（例如 `yourdomain.com`）時：

### 1. DNS 設定
```
A     app.yourdomain.com       -> 172.237.11.179
A     admin.yourdomain.com     -> 172.237.11.179
A     api.yourdomain.com       -> 172.237.11.179
A     admin-api.yourdomain.com -> 172.237.11.179
A     grafana.yourdomain.com   -> 172.237.11.179
A     *.yourdomain.com         -> 172.237.11.179  # wildcard
```

### 2. 更新環境變數
編輯 `.env.production`，全域替換：
```bash
172-237-11-179.sslip.io → yourdomain.com
```

### 3. 更新 Nginx 配置
編輯 `nginx/gateway.conf`，全域替換：
```bash
172-237-11-179.sslip.io → yourdomain.com
```

### 4. 重新申請 SSL
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

### 5. 重啟服務
```bash
docker compose -f docker-compose.prod.yml restart gateway
docker compose -f docker-compose.prod.yml restart web
```

---

## 故障排除

### 無法存取服務
```bash
# 檢查防火牆
ufw status

# 檢查 Docker 服務
docker compose -f docker-compose.prod.yml ps

# 檢查 Gateway 日誌
docker compose -f docker-compose.prod.yml logs gateway
```

### SSL 憑證取得失敗
- 確認 80 port 未被佔用（Gateway 需暫停）
- 確認 DNS 已正確解析：`dig app.172-237-11-179.sslip.io`
- 檢查防火牆是否允許 80 port

### 資料庫連線錯誤
```bash
# 檢查 PostgreSQL
docker compose -f docker-compose.prod.yml exec postgres pg_isready

# 檢查密碼
grep POSTGRES_PASSWORD .env.production
```

### Worker 任務不執行
```bash
# 檢查 Redis
docker compose -f docker-compose.prod.yml exec redis redis-cli -a <REDIS_PASSWORD> ping

# 檢查 Worker 日誌
docker compose -f docker-compose.prod.yml logs worker

# 重啟 Worker
docker compose -f docker-compose.prod.yml restart worker
```

---

## 安全建議

### 1. 限制 SSH 存取
```bash
# 只允許特定 IP SSH
ufw delete allow 22/tcp
ufw allow from <YOUR_IP> to any port 22
```

### 2. Admin 介面 IP 白名單
編輯 `nginx/gateway.conf`，在 admin server block 中：
```nginx
# Optional: IP whitelist for admin
allow <YOUR_OFFICE_IP>;
deny all;
```

### 3. 定期更新系統
```bash
apt update && apt upgrade -y
```

### 4. 監控異常存取
- Grafana 查看 Nginx access logs
- 定期檢查 `docker compose logs`

---

## 聯絡與支援
- GitHub: https://github.com/stevechen1112/aihr
- 詳細文件: [docs/LINODE_DEPLOYMENT.md](../docs/LINODE_DEPLOYMENT.md)
