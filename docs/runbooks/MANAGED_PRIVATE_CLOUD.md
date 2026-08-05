# 託管私有雲 Runbook（Phase 1 — 形態 B）

**產品**：Enclave Triple Injection — 託管私有雲（每客戶獨立 Compose 實例）  
**對象**：維運／交付團隊（Sales-Led 開戶後由後台或 agent 拉起）  
**最後更新**：2026-08-05

> 對齊 `docs/CLOUD_AND_COMMERCIALIZATION_PLAN.md` §5.10 WS-GTM-OPS、§Phase 1 出口。  
> 本 runbook 描述**單一客戶實例**的拉起、驗收與日常維運；fleet 級監控屬 WS-AGENTIC-OPS（人類僅在「確認交付」介入）。

---

## 1. 架構摘要

| 項目 | 託管 POC／生產預設 |
|------|-------------------|
| 隔離 | **實例級**（一客一 VM／VPC，不做共享多租戶） |
| 編排 | Docker Compose（`docker-compose.prod.yml` + overlay） |
| 儲存 | `STORAGE_BACKEND=s3` + Cloudflare R2／Linode Objects |
| 安全 | ClamAV fail-closed、三層限流、Owner MFA、SSO（Business+） |
| 觀測 | Sentry + Langfuse（可選）+ 既有 Prometheus／Grafana |
| 金流 | NewebPay（CG-PAY，Phase 1 待接） |

---

## 2. 前置條件

1. 已複製並填寫 `.env.production`（自 `.env.production.example`）。  
2. 雲端物件儲存 bucket 已建（每客戶獨立 bucket 或前綴）。  
3. LLM／Embedding API 金鑰就緒（雲端零 GPU：Voyage embedding + 雲端 LLM）。  
4. （Business+）IdP OAuth 應用與 `TenantSSOConfig` 設定路徑已知。  
5. 邊緣 TLS／WAF（Cloudflare 等）已指到該 VM（見下方 §2.2）。

### 2.1 託管必開環境變數（摘要）

```bash
APP_ENV=production
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com
S3_BUCKET=enclave-<customer-slug>
S3_ACCESS_KEY=...
S3_SECRET_KEY=...

CLAMAV_ENABLED=true
CLAMAV_HOST=clamav
CLAMAV_PORT=3310
CLAMAV_FAIL_CLOSED=true

RATE_LIMIT_ENABLED=true
MFA_ENFORCE_OWNER=true
EMAIL_VERIFICATION_ENABLED=true

# 可選觀測
SENTRY_DSN=
LANGFUSE_ENABLED=false
```

完整清單見 `.env.production.example` 與 `.env.example` 的 CG-* 段落。

### 2.2 Cloudflare WAF／TLS（WS-SECURITY）

Phase 1 邊緣建議最低設定（帳號／DNS 需人工）：

1. 橙雲代理至託管 VM；強制 HTTPS（Full/Strict）。  
2. WAF：Managed ruleset 預設；封鎖常見掃描路徑。  
3. Rate limiting 規則：邊緣 IP 層（與應用三層限流互補）。  
4. 僅允許 Cloudflare／信任代理 IP 進 origin（或 firewall 僅 443←CF）。  
5. NotifyURL（`/api/v1/payment/notify`）勿被 Bot Fight 誤擋；必要時 Bypass。

---

## 3. 拉起實例

### 3.1 Standard pack（RAGFlow + 可選 sidecar）

```bash
docker compose \
  --env-file .env.production \
  --env-file compose/image-pins.env \
  --env-file compose/pack-enabled.env \
  -f docker-compose.prod.yml \
  -f compose/sidecars.yml \
  -f compose/clamav.yml \
  --profile production up -d
```

> `compose/clamav.yml` 在 `production` profile 下注入 ClamAV sidecar 並設定 web `CLAMAV_*`。  
> 地端開發可省略 `-f compose/clamav.yml` 並保持 `CLAMAV_ENABLED=false`。

### 3.2 資料庫遷移

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml \
  exec web alembic upgrade head
```

首次部署：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml \
  exec web python scripts/initial_data.py
```

### 3.3 Preflight

```bash
python scripts/preflight_check.py --profile standard --json
python scripts/ops_lifecycle.py preflight --profile standard
```

---

## 4. 開戶（Sales-Led）

1. **平台 superuser** 建立租戶（方案：`pilot`／`team`／`business`／`enterprise`）。  
2. 建立 **owner** 帳號；若 `MFA_ENFORCE_OWNER=true`，owner 首次登入須完成 TOTP。  
3. 若啟用 SSO：owner 於 `/api/v1/sso/...` 設定 IdP（預設 **不自動開戶**）。  
4. 邀請首批使用者（≤ 方案人數上限）。  
5. 記錄：`tenant_id`、實例 URL、bucket 名稱、支援聯絡人。

配額矩陣見計畫 §3.3；超額回 **429**（查詢／token／儲存三軸）。

---

## 5. POC 煙霧測試（交付閘門）

在實例 URL 就緒且 owner 已建立後：

```bash
export ENCLAVE_URL=https://<customer>.example.com
export POC_OWNER_EMAIL=owner@customer.com
export POC_OWNER_PASSWORD='...'

python scripts/managed_poc_smoke.py
```

通過條件：`artifacts/managed_poc_smoke_last_run.json` 的 `status` 為 `PASS`。

發布前另跑雲端閘門：

```bash
python scripts/cloud_release_gate.py --strict
python scripts/cloud_release_gate.py --run-pytest --strict   # 含全量 pytest
```

僅健康檢查（無憑證時）：

```bash
python scripts/managed_poc_smoke.py --skip-auth
```

檢查項：

| # | 項目 | 失敗時 |
|---|------|--------|
| 1 | `/health` | 容器／遷移／依賴未就緒 |
| 2 | Gateway health | Sidecar 或 pack 未掛 |
| 3 | Owner JWT 登入 | 帳密／MFA／email verify |
| 4 | `/company/usage/summary` | 配額／audit 表異常 |
| 5 | 上傳 sample PDF | ClamAV／S3／配額 |
| 6 | Chat（可 `--skip-chat`） | LLM 路由或配額 |

人類 **確認交付** 前須煙霧全綠 + 盲測 10 題（Sales-Led 清單，見計畫 §5.10）。

---

## 6. 備份與 DR

```bash
python scripts/ops_lifecycle.py backup
```

- DB：`pg_dump` → `artifacts/ops/` + 異地副本  
- 物件：R2／S3 生命週期 + 跨區複製（依 DPA）  
- **季度 restore drill** → `HG-DR-SIGN`（需客戶簽核）

RPO 目標 ≤ 24h、RTO ≤ 8h（Phase 1）。

---

## 7. 升級

1. `python scripts/ops_lifecycle.py backup`  
2. 拉取鎖定 digest 映像（`compose/image-pins.env`）  
3. `python scripts/ops_lifecycle.py upgrade --revision head`  
4. `python scripts/managed_poc_smoke.py` 重跑  
5. 失敗 → `rollback --steps 1` 並還原映像 digest

---

## 8. 監控與事件

| 信號 | 來源 |
|------|------|
| API 錯誤率 | Sentry（若已設 `SENTRY_DSN`） |
| 問答 trace | Langfuse |
| 配額拒絕 | Prometheus `enclave_quota_exceeded_total` |
| 溯源稽核 | `enclave_source_verify_total` |
| 基礎設施 | Grafana（`docker-compose.prod.yml` monitoring 段） |

MTTD 目標 < 15 分鐘（Phase 1）。

---

## 9. 常見故障

| 症狀 | 檢查 |
|------|------|
| 上傳 503「安全掃描」 | `docker compose ... ps clamav`；ClamAV health；`CLAMAV_FAIL_CLOSED` |
| 上傳 429 儲存 | `/company/usage/summary`；S3 是否寫入成功 |
| SSO 登入後 403 | 網域白名單；`auto_create_user=false` 時須預建帳號 |
| MFA 無法完成 | partial token 不可存取受保護 API；須走 `/auth/mfa/verify` |
| Sidecar unhealthy | 是否同時掛 `sidecars.yml` + `pack-enabled.env` |
| S3 403 | bucket policy、`S3_ENDPOINT_URL`、租戶前綴 |

---

## 10. 人工閘門（本 runbook 不自動完成）

| ID | 項目 |
|----|------|
| HG-PENTEST-CLOUD | 針對託管環境的外部滲透 |
| HG-LEGAL | DPA／模型商用授權 |
| HG-DR-SIGN | 客戶現場還原簽核 |
| CG-PAY | NewebPay 金流 E2E |
| CG-STORAGE | S3 雙路徑**雲端帳號**實測（程式層已完成） |

---

## 11. 相關文件

- `docs/CLOUD_AND_COMMERCIALIZATION_PLAN.md` — Phase 1 總路線  
- `docs/runbooks/PILOT_SUPPORT.md` — 地端 Pilot（形態 A）  
- `compose/README.md` — overlay 組合  
- `docs/OPEN_GATES.md` — CG-* 閘門狀態  
