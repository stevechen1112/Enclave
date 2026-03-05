# Enclave 地端部署安裝手冊

> **版本：** v1.0　｜　**適用環境：** Linux / macOS / Windows Server

---

## 一、硬體需求

| 情境 | 最低需求 | 建議配置 |
|---|---|---|
| 使用雲端 API（Gemini / OpenAI） | 4 核 CPU、8 GB RAM、50 GB SSD | 8 核、16 GB RAM、200 GB SSD |
| 使用 Ollama 本機 LLM | 8 核 CPU、16 GB RAM、100 GB SSD | 獨立 GPU（8 GB VRAM 以上）、32 GB RAM |

> **說明：** 雲端 API 模式下（Gemini / OpenAI），LLM 推論在雲端執行，本機只需足夠的記憶體給 PostgreSQL + pgvector 使用。  
> Ollama 模式下，LLM 推論在本機執行，效能主要取決於 CPU/GPU 和記憶體。

---

## 二、前置條件

### 所有平台

- **Docker Engine 24+** 與 **Docker Compose v2**
- **Python 3.11+**（用於執行安裝腳本）
- 網路連線（僅首次安裝需要拉取 Docker 映像檔）

### Linux / macOS

```bash
# 安裝 Docker（若尚未安裝）
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
```

### Windows

1. 安裝 [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
2. 確認 WSL 2 已啟用
3. 使用 **PowerShell**（以系統管理員身份執行）

---

## 三、安裝步驟

### 步驟 1：取得程式碼

```bash
# 從 USB / 網路共享 / Git 取得
cp -r /media/usb/enclave /opt/enclave
cd /opt/enclave
```

### 步驟 2：設定環境變數

```bash
cp .env.example .env
```

編輯 `.env`，**必填項目**：

```env
# 管理員設定
FIRST_SUPERUSER_EMAIL=admin@your-domain.local
FIRST_SUPERUSER_PASSWORD=至少12字元的強密碼

# 安全金鑰（執行以下指令產生）
# python gen_hash.py
SECRET_KEY=<產生的金鑰>

# 資料庫密碼
POSTGRES_PASSWORD=<資料庫密碼>

# LLM 設定（三選一）
# ── 選項 A：Google Gemini（推薦，性價比高）──
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-3-flash-preview

# ── 選項 B：OpenAI API ──
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-...
# OPENAI_MODEL=gpt-4o-mini

# ── 選項 C：Ollama 本機 LLM（零 API 費用，需要較強硬體）──
# LLM_PROVIDER=ollama
# OLLAMA_BASE_URL=http://host.docker.internal:11434
# OLLAMA_MODEL=llama3.2

# 向量嵌入設定（二選一）
# ── 預設：Ollama 本機嵌入（免費，推薦地端）──
EMBEDDING_PROVIDER=ollama
OLLAMA_EMBED_MODEL=bge-m3
# ── 雲端 Voyage AI（品質較高，需 API Key）──
# EMBEDDING_PROVIDER=voyage
# VOYAGE_API_KEY=pa-...
```

### 步驟 3：執行環境檢查

```bash
python scripts/check_env.py
```

所有項目通過後繼續。

### 步驟 4：一鍵安裝

**Linux / macOS：**
```bash
bash scripts/setup.sh
```

**Windows（PowerShell）：**
```powershell
.\scripts\setup.ps1
```

安裝腳本會自動完成：
- 建置 Docker 映像檔
- 啟動所有服務（API、前端、資料庫、Redis、Worker）
- 執行資料庫 Migration
- 建立管理員帳號

---

## 四、Ollama 本機 LLM 設定

若要使用零 API 費用的本機模式：

```bash
# 安裝 Ollama（Linux）
curl -fsSL https://ollama.com/install.sh | sh

# 下載中文推薦模型
ollama pull llama3.2          # 3B 參數，較快
ollama pull qwen2.5:7b        # 7B 參數，中文能力較強

# 測試
ollama run qwen2.5:7b "請用繁體中文介紹自己"
```

在 `.env` 中設定：
```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5:7b
```

> **注意：** Docker 容器內使用 `host.docker.internal` 連到宿主機的 Ollama。  
> Linux 宿主機若找不到此位址，請改用實際 IP（如 `http://172.17.0.1:11434`）。

---

## 五、Phase 10 Agent 資料夾監控設定

安裝完成後，若要啟用自動索引：

```env
AGENT_WATCH_ENABLED=true
# 掛載到容器內的路徑（需與 docker-compose.yml volumes 對應）
AGENT_WATCH_FOLDERS=/data/contracts,/data/reports
AGENT_BATCH_HOUR=2          # 每天凌晨 2 點執行
AGENT_MAX_CPU_PERCENT=50.0  # 最多使用 50% CPU
```

在 `docker-compose.yml` 中掛載宿主機資料夾：
```yaml
services:
  web:
    volumes:
      - /path/on/host/contracts:/data/contracts:ro
      - /path/on/host/reports:/data/reports:ro
```

---

## 六、服務管理

```bash
# 停止所有服務
docker compose stop

# 重新啟動
docker compose start

# 查看即時日誌
docker compose logs -f

# 查看特定服務日誌
docker compose logs -f web
docker compose logs -f worker

# 完整重建（更新後執行）
docker compose down
docker compose build
docker compose up -d
docker compose exec web alembic upgrade head
```

---

## 七、資料備份

```bash
# 備份 PostgreSQL 資料庫
docker compose exec db pg_dump -U postgres enclave > backup_$(date +%Y%m%d).sql

# 備份 uploads 目錄
tar czf uploads_$(date +%Y%m%d).tar.gz uploads/

# 還原資料庫
docker compose exec -T db psql -U postgres enclave < backup_20260101.sql
```

建議每日自動備份，參考 [scripts/backup.sh](../scripts/backup.sh)。

---

## 八、常見問題

### Q: 資料庫連線失敗
```
sqlalchemy.exc.OperationalError: could not connect to server
```
**解決：** `docker compose logs db` 確認資料庫是否正常啟動，等待 10-20 秒後重試。

### Q: Ollama 連線失敗
```
httpx.ConnectError: [Errno 111] Connection refused
```
**解決：** 確認 Ollama 在宿主機上正在執行（`ollama list`），並確認 `OLLAMA_BASE_URL` 設定正確。

### Q: 文件上傳失敗（大檔案）
**解決：** 修改 `nginx/gateway.conf` 中的 `client_max_body_size`，預設 100MB。

### Q: 向量搜尋品質差
**解決：** 確認 `EMBEDDING_PROVIDER` 設定正確：
- `EMBEDDING_PROVIDER=ollama`（預設）：確認 Ollama 正在執行且已下載 `bge-m3` 模型（`ollama pull bge-m3`）。
- `EMBEDDING_PROVIDER=voyage`：確認 `VOYAGE_API_KEY` 有效。

### Q: Gemini API 呼叫失敗
```
httpx.HTTPStatusError: 400 Bad Request
```
**解決：** 確認 `GEMINI_API_KEY` 已正確填入，且有存取 `gemini-3-flash-preview` 模型的權限．可至 [Google AI Studio](https://aistudio.google.com/) 確認 API 金鑰狀態。

---

## 九、網路安全建議

- ✅ 對外只開放 80/443（Nginx）與 SSH 端口，後端 API 8000 及資料庫 5432 不對外暴露
- ✅ 啟用防火牆，封鎖所有不必要端口
- ✅ 定期更換 `SECRET_KEY` 和資料庫密碼
- ✅ 若需行動端遠端存取，使用 **Tailscale** 或 **WireGuard VPN**，而非直接開放端口
- ✅ 啟用磁碟加密（BitLocker / dm-crypt）保護靜態資料

### 行動端 VPN 詳細設定

行動端 App（iOS / Android）遠端連線的完整設定步驟，請參閱：

📱 **[行動端 VPN / Zero Trust 連線設定指南](MOBILE_VPN_GUIDE.md)**

涵蓋：Tailscale 設定（建議首選）、WireGuard 自建 VPN、直接 HTTPS 三種方案，以及各方案的安全檢查清單與常見問題排查。

---

文件版本：v1.1（2026-03-06）｜ Enclave 私有專案
