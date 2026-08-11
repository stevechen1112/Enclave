# Enclave 全雲端化與 Linode 部署評估

文件版本：1.0
建立日期：2026-08-06
狀態：評估完成，部署工件已備妥
關聯文件：`LINODE_DEPLOYMENT.md`（舊版操作手冊，本文件為準）、`CLOUD_AND_COMMERCIALIZATION_PLAN.md`

---

## 1. 結論摘要

| 問題 | 結論 |
|------|------|
| Enclave 可以全雲端嗎？ | **可以。** 核心棧已完全容器化，無任何必須落地在本機的相依。唯一「本地模型」相依是 Ollama embedding（bge-m3），可改用 CPU 容器或雲端 embedding API 解決。 |
| 可以部署到 Linode 嗎？ | **可以。** 建議 Linode 8GB Shared（約 US$48/月）單機跑完整核心棧；不需要 GPU。 |
| 需要 GPU 嗎？ | **不需要。** LLM 走 OpenAI/Gemini 雲端 API、STT 走 OpenAI gpt-transcribe、embedding 的 bge-m3 在 CPU 上可跑（或換 Voyage）。RAGFlow/WeKnora/PipesHub 三個重型 sidecar 在雲端 PoC 階段關閉。 |

**推薦架構（PoC～初期商用）**：單台 Linode 8GB + Docker Compose + 雲端 LLM API + Linode Object Storage（備份）。月成本約 **US$50–60 + LLM API 用量費**。

---

## 2. 系統架構盤點（部署相依）

### 2.1 核心服務（必需，已全部容器化）

| 服務 | 映像 | 記憶體上限 | 說明 |
|------|------|-----------|------|
| web | 自建（python:3.13-slim） | 1G | FastAPI，uvicorn 2 workers |
| worker | 同上 | 1G | Celery 文件解析/任務 |
| worker-beat | 同上 | 256M | Celery 排程（outbox/對帳） |
| db | pgvector/pgvector:pg16 | 2G | PostgreSQL + pgvector |
| redis | redis:7-alpine | 512M | broker + cache |
| frontend | 自建（node build → nginx） | 64M | React SPA 靜態檔 |
| gateway | nginx:1.25-alpine | 128M | 反向代理 + rate limit |
| prometheus / grafana | 官方映像 | 512M / 256M | 監控（可選） |

核心合計約 **4.2GB（不含監控）/ 5GB（含監控）**。

### 2.2 外部相依（雲端化的關鍵判斷）

| 相依 | 目前本機做法 | 雲端方案 | 判斷 |
|------|-------------|----------|------|
| LLM 推論 | OpenAI API（`LLM_PROVIDER=openai`） | 不變，雲端 API | ✅ 無障礙 |
| 語音 STT | OpenAI gpt-transcribe | 不變，雲端 API | ✅ 無障礙 |
| Embedding | 本機 Ollama bge-m3（1024 維） | A. compose 內跑 CPU 版 Ollama（+1.5GB RAM）<br>B. 換 Voyage/OpenAI embedding | ✅ 兩條路都可；**注意：換 provider 會改向量維度，既有文件需全部重嵌入**，建議選 A 無痛遷移 |
| 文件解析 | 原生解析器（.md/.docx/.xlsx）＋ LlamaParse（掃描 PDF） | 不變；LlamaParse 是雲端 API | ✅ 無障礙 |
| 檔案儲存 | 本地 `uploads/` volume | 本地 volume 或 `STORAGE_BACKEND=s3` 接 Linode Object Storage | ✅ 已內建 S3 支援 |
| RAGFlow | Docker sidecar（要 GPU） | **關閉**（`RAGFLOW_ENABLED=false`） | ⚠️ 見 §4 |
| WeKnora / PipesHub | Docker sidecar（要 Neo4j/Mongo） | **關閉** | ⚠️ 見 §4 |

### 2.3 重型 sidecar 的取捨

RAGFlow / WeKnora / PipesHub 是「三重注入」計畫的能力增強層，**不是核心產品的必要條件**：

- 本機 E2E 已證明：`.md/.docx/.xlsx` 走原生解析器即可完整入庫與檢索（`RAGFLOW_FORCE_PARSE=false`）。
- 三者在雲端要正常跑需要 GPU（RAGFlow/Ollama 推論）＋額外 6–8GB RAM，Linode GPU 實例月費 US$1000 起，**PoC 階段不值得**。
- 建議：雲端第一期 `RAGFLOW_ENABLED=false`、`WEKNORA_ENABLED=false`、`PIPESHUB_ENABLED=false`。未來若需要掃描版 PDF 的高精度解析，用 LlamaParse（雲端 API）補足即可。

---

## 3. Linode 規格與成本評估

### 3.1 方案比較

| 方案 | 規格 | 月費（約） | 適用 |
|------|------|-----------|------|
| **A. 最小可行** | Shared 4GB（2 vCPU/80GB） | US$24 | 純 demo；關監控、embedding 換 Voyage。RAM 吃緊，不建議久用 |
| **B. 推薦** | Shared 8GB（4 vCPU/160GB） | US$48 | 核心棧＋CPU embedding＋監控全開，10–30 人團隊 PoC |
| **C. 成長** | Dedicated 8GB 或 Shared 16GB | US$72–96 | 正式商用、文件量大、併發高 |

另加：Linode Object Storage 250GB US$5/月（備份＋上傳檔）、備份服務（Linode Backups）約月費 20%。

> 價格為 2026 年牌價概估，下單前請以 Linode 官網為準。

### 3.2 單機 vs 託管服務

| 元件 | 單機 Docker（第一期） | 託管化（規模化後） |
|------|---------------------|-------------------|
| PostgreSQL | 容器＋每日 `scripts/backup.sh` | Linode Managed PostgreSQL |
| 檔案 | 本地 volume | Object Storage（S3 相容，程式已支援） |
| 高可用 | 單點，重啟自動恢復 | NodeBalancer＋雙節點 |

第一期單機即可，資料庫備份每日上傳 Object Storage 就有基本保障。

---

## 4. 本次評估發現的部署缺口（已修補）

評估過程對照「目前產品實際狀態」與「既有部署工件」，發現 5 個會導致部署後功能缺失或異常的缺口，**本次已全部修補**：

| # | 缺口 | 後果 | 修補 |
|---|------|------|------|
| 1 | `.env.production.example` 缺少 MKA 功能旗標 | 新部署後 `FIXED_FORM_ENABLED`/`KNOWHOW_CARD_ENABLED` 預設 False → **表單、知識卡、訪談模式整個消失** | 已在範本補上 MKA 旗標區段（預設開啟） |
| 2 | nginx gateway 未處理 SSE | `/api/v1/chat/stream` 串流回應會被 proxy buffering 卡住，聊天「打字機」效果失效 | `gateway.conf` 新增 SSE 專用 location（`proxy_buffering off`） |
| 3 | `deploy_linode.sh` 是舊專案（aihr）遺物 | 寫死舊 IP、舊 repo、舊路徑 `/opt/aihr`，直接跑會部署錯誤代碼 | 全部參數化重寫（IP/網域/repo 皆為參數） |
| 4 | `verify_deployment.sh` 與 gateway 矛盾 | gateway 已封鎖 `/docs`（回 403），驗證腳本卻期待 200 → 永遠報失敗 | 重寫：改驗證 `/health`、登入 API、MKA 路由 |
| 5 | prod compose 無 embedding 服務 | `OLLAMA_EMBED_URL` 預設指向 `host.docker.internal`，雲端主機上沒有 Ollama → 文件入庫全失敗 | prod compose 新增 `ollama-embed` CPU 服務（profile 控制） |

---

## 5. 部署工件清單（本次已備妥）

| 檔案 | 狀態 | 說明 |
|------|------|------|
| `docker-compose.prod.yml` | 已更新 | 新增 `ollama-embed`（CPU，profile=embed）與 embedding URL 接線 |
| `.env.production.example` | 已更新 | 補 MKA 旗標、embedding 雙方案、sidecar 預設關閉 |
| `nginx/gateway.conf` | 已更新 | SSE 串流修正 |
| `scripts/deploy_linode.sh` | 已重寫 | 參數化一鍵部署（含 migration、初始資料、驗證） |
| `scripts/verify_deployment.sh` | 已重寫 | 對齊現行路由與安全策略 |
| `scripts/generate_secrets.py` | 沿用 | 自動生成 SECRET_KEY/DB/Redis/Grafana 密碼 |
| `scripts/backup.sh` | 沿用 | 每日 DB 備份 |

---

## 6. 上線步驟速查（詳細版在部署腳本註解）

```bash
# 1. Linode 開一台 Ubuntu 24.04（8GB Shared），記下 IP
# 2. 本機把代碼推上 GitHub（或私有 repo）
# 3. SSH 上主機，一鍵部署：
curl -fsSL https://get.docker.com | sh
git clone <your-repo> /opt/enclave && cd /opt/enclave
cp .env.production.example .env.production
python3 scripts/generate_secrets.py --output .env.production
vim .env.production   # 填 OPENAI_API_KEY、FIRST_SUPERUSER_*、網域
bash scripts/deploy_linode.sh --ip <IP> --domain app.<IP 用 dash>.sslip.io
# 4. 驗證
bash scripts/verify_deployment.sh
```

之後申請 Let's Encrypt（sslip.io 也支援）即可上 HTTPS，步驟同 `LINODE_DEPLOYMENT.md` §7。

---

## 7. 風險與後續建議

| 風險 | 等級 | 緩解 |
|------|------|------|
| 單機單點故障 | 中 | 每日備份至 Object Storage；Linode Backups；故障時 30 分鐘內可重建 |
| CPU embedding 在高併發下入庫變慢 | 低–中 | bge-m3 CPU 約 1–3 秒/文件批次，PoC 足夠；量大時換 Voyage 或升級 vCPU |
| LLM API 費用隨用量成長 | 中 | 既有 `MKATaskCost` 成本追蹤＋租戶 quota；Gemini flash 層級壓低成本 |
| 掃描版 PDF 解析品質（無 RAGFlow） | 低 | LlamaParse 雲端 API 補足（`LLAMAPARSE_ENABLED=true`） |
| 未來多用戶 SaaS 化 | — | 依 `CLOUD_AND_COMMERCIALIZATION_PLAN.md` 推進 RLS/SSO/quota，與本次部署不相衝突 |

---

## 8. 部署實績（2026-08-06 上線）

**系統已於 http://172.233.78.116 上線**，驗證 15/15 通過（容器、端點、登入、MKA 路由、DB/Redis/Ollama）。

| 項目 | 結果 |
|------|------|
| 主機 | Linode 8GB / 4 vCPU / 157GB（大阪），Ubuntu 24.04，Docker 29.7.2 |
| 部署方式 | tarball 上傳 `/opt/enclave`（未經 git；本地有未提交變更） |
| 容器 | web / worker / worker-beat / db / redis / gateway / frontend / ollama-embed / prometheus / grafana 共 10 個 |
| DB migration | 升至 `mka_p3_knowhow_owner_001`（最新） |
| Embedding | ollama-embed 容器已拉取 bge-m3 |
| 管理員 | `admin@kachu.tw`（隨機強密碼，另存於主機 `/opt/enclave/.env.production`） |
| SSH | 金鑰 `~/.ssh/kachu_enclave_ed25519`，config 別名 `ssh kachu` |

**部署中實際修復的問題**（已回寫 repo）：

1. 前端 3 個 TS 建置錯誤（`KnowhowDetailPage.tsx` JSX 未閉合、`ApprovalTimeline.tsx` 未用 import、`FormPage.tsx` unknown 型別）——vite dev 不會發現，僅 `npm run build` 會踩到。
2. `verify_deployment.sh`：登入路徑 `/auth/login` → `/auth/login/access-token`；`/modules` → `/job-modules`；全部 compose 指令補 `--env-file`。
3. `deploy_linode.sh`：`initial_data.py` 需先 `docker cp scripts` 進容器（`.dockerignore` 排除 scripts/）並帶 `PYTHONPATH=/code`。
4. `docker-compose.prod.yml`：worker-beat 停用繼承的映像健康檢查（beat 無 HTTP port，否則永遠 unhealthy）。

**刻意取捨**：`CLAMAV_ENABLED=false`（8GB RAM 不足以同時承載 ClamAV 約 2GB；正式商用應以 `compose/clamav.yml` 開啟或升級記憶體）。`LLAMAPARSE_ENABLED=false`（無 API key，掃描版 PDF 暫不支援）。

**待辦**：~~kachu.tw DNS（GoDaddy）A 記錄改指 `172.233.78.116`（含 www），生效後申請 Let's Encrypt 上 HTTPS。~~ **已完成（2026-08-06）**：

- DNS 已切換，`kachu.tw` / `www.kachu.tw` → `172.233.78.116`
- Let's Encrypt 憑證已簽發（雙網域，效期至 2026-11-04），`certbot renew` 模擬續期成功
- 續期 hooks 已設定（`/etc/letsencrypt/renewal-hooks/{pre,post}/` 自動停/起 gateway）
- 新增 `nginx/gateway-ssl.conf`（HTTP→HTTPS 301、HSTS、TLSv1.2/1.3），compose 以 `GATEWAY_CONF` 切換
- **https://kachu.tw 正式上線**，HTTPS 全量驗證 15/15 通過

**DEMO 環境（2026-08-06 就緒）**：5 個測試帳號（sales/field/master/newcomer/viewer@demo.mka，密碼 Demo12345）、5 個職能模組、T01–T03 公司版型、EQ-100 場景、21 份測試文件已入庫；業務劇本 A2 實測 16.8s 正確命中版本差異錨點。語音（OpenAI STT/TTS）實測可用。

**上線後追加修復**（皆已回寫 repo）：生產 env 未寫入 OpenAI/Gemini key（example 註解行未被替換）；`config.py` 缺 `METRICS_INTERNAL_ONLY`（/metrics 500）；限流器與 embedding 快取連 Redis 未帶密碼（NOAUTH 退化）；uploads volume 擁有者 root 導致上傳 500（chown 999）；ollama-embed 加 `OLLAMA_KEEP_ALIVE=-1`（bge-m3 冷載 119s 會拖垮檢索）；gateway chat 逾時 120s→300s。

**生產 E2E 走查（2026-08-06 晚，26/26 通過）**：對 https://kachu.tw 完整跑 `test-materials/e2e/e2e_walkthrough.py` 三劇本＋權限邊界。首輪 25/26，A2 版本差異問答失敗；根因查明為**檢索上下文組裝缺陷**——`chat_orchestrator._build_context` 直接取多步編排結果的前 5 段，但該結果是「依文件分組」而非依分數排序，導致 D01b（v2.0）的 5 個 chunk 佔滿上下文、D01c（v2.1）內容進不了 LLM（catalog 臂只給檔名）。修復：非檔名鎖定查詢改為「依分數排序＋每文件最多 2 段」的多樣性選取（比較型問題必需）；D01c 文件亦補上版本差異摘要（良好文件實務）。修復後兩種問法皆 3/3 命中錨點，E2E 26/26。走查殘留資料已以 `cleanup_prod_e2e.py` 清除（6 審核／6 表單／2 知識卡／19 對話），線上恢復乾淨 DEMO 狀態。本地 gates 28/28 通過（期間發現本機 shell 有殘留 `POSTGRES_PASSWORD=dummy` 環境變數污染測試連線，移除後正常，與程式無關）。
