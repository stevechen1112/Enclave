# Enclave 運維 SOP（標準作業程序）

> 版本: 1.0 | 更新日期: 2026-02-07 | 維護者: DevOps Team

---

## 目錄

1. [部署流程 SOP](#1-部署流程-sop)
2. [回滾流程 SOP](#2-回滾流程-sop)
3. [資料庫維護 SOP](#3-資料庫維護-sop)
4. [事故應對 SOP](#4-事故應對-sop)
5. [值班與通知排程](#5-值班與通知排程)
6. [日常運維檢查表](#6-日常運維檢查表)

---

## 1. 部署流程 SOP

### 1.1 Staging 部署（自動）

**觸發條件：** Push to `main` branch

**流程：**
```
git push origin main
    │
    ▼
GitHub Actions (deploy-staging.yml)
    │
    ├── 1. Run tests
    ├── 2. Build Docker image
    ├── 3. Push to registry (tag: staging-{sha})
    ├── 4. SSH to staging server
    ├── 5. Pull new image
    ├── 6. Run alembic upgrade head
    ├── 7. docker compose up -d
    └── 8. Health check verification
```

**預估時間：** 5-10 分鐘

**驗證步驟：**
1. 檢查 GitHub Actions 執行結果（綠勾）
2. 確認 Staging 環境健康：`curl https://staging.yourdomain.com/health`
3. 執行冒煙測試：登入 → 聊天 → 文件上傳

### 1.2 Production 部署（手動觸發）

**觸發條件：** GitHub Actions 手動 Dispatch

**前置準備：**
- [ ] Staging 環境驗證通過
- [ ] 所有 P1/P2 Bug 已修復
- [ ] Migration 已在 Staging 驗證
- [ ] 團隊已通知部署時間
- [ ] 已確認備份完成

**流程：**
```
GitHub → Actions → deploy-production.yml → Run workflow
    │
    ▼
    ├── 1. 自動備份（DB snapshot）
    ├── 2. Build Docker image (tag: prod-{sha})
    ├── 3. Push to registry
    ├── 4. SSH to production
    ├── 5. Pull new image
    ├── 6. Run alembic upgrade head
    ├── 7. Rolling restart (zero-downtime)
    │      ├── Stop worker 1 → Start new → Health check ✓
    │      ├── Stop worker 2 → Start new → Health check ✓
    │      ├── Stop worker 3 → Start new → Health check ✓
    │      └── Stop worker 4 → Start new → Health check ✓
    ├── 8. Post-deploy health check
    └── 9. Notify team (Slack/Email)
```

**預估時間：** 10-15 分鐘

**部署後驗證（5 分鐘內完成）：**
1. `curl https://app.yourdomain.com/health` → 200
2. `curl https://app.yourdomain.com` → 200
3. 登入測試帳號確認功能正常
4. 檢查 Grafana — 錯誤率無異常升高
5. 檢查 Prometheus — 無 alert firing

### 1.3 緊急部署（Hotfix）

**觸發條件：** P1 事故需要立即修復

**流程：**
1. 從 `main` 建立 `hotfix/issue-xxx` 分支
2. 修復問題並推送
3. 建立 PR → 1 人 fast review → merge
4. 手動觸發 Production 部署
5. 驗證修復

**注意：**
- Hotfix 不需走完整 Staging 驗證流程
- 但仍需至少 1 人 code review
- 部署後密切監控 30 分鐘

---

## 2. 回滾流程 SOP

### 2.1 何時回滾

在以下情況立即回滾：
- 部署後 5 分鐘內發現 P1 問題
- 錯誤率超過 5%
- API 回應時間 P95 超過 5 秒
- 核心功能（登入、聊天）無法使用

### 2.2 快速回滾步驟

```bash
# 1. SSH 到 Production 伺服器
ssh deploy@prod.yourdomain.com

# 2. 查看可用的映像版本
docker images | grep enclave | head -10

# 3. 切換到上一版映像
cd /opt/enclave
export IMAGE_TAG=prod-<previous-sha>
docker compose -f docker-compose.prod.yml up -d web worker

# 4. 驗證回滾
curl https://app.yourdomain.com/health

# 5. 如果有 DB migration 需要回滾
docker compose exec web alembic downgrade -1
```

**或使用 GitHub Actions 回滾（推薦）：**

```
GitHub → Actions → deploy-production.yml → Run workflow
  → 填入 "rollback" 和目標 commit SHA
```

### 2.3 DB Migration 回滾

```bash
# 回滾一個版本
docker compose exec web alembic downgrade -1

# 回滾到指定版本
docker compose exec web alembic downgrade <revision_id>

# 查看 migration 歷史
docker compose exec web alembic history
```

**⚠️ 注意：**
- Migration 回滾前確認是否有 destructive 操作（DROP COLUMN 等）
- 建議在 Staging 先測試 downgrade
- 若 migration 不可逆，需手動修復

### 2.4 回滾後處理

1. 確認服務恢復正常
2. 通知團隊回滾完成
3. 建立事故報告
4. 分析失敗原因
5. 修復後重新走部署流程

---

## 3. 資料庫維護 SOP

### 3.1 定期備份

**自動備份（每日 02:00 UTC）：**

```bash
# 排程已設定在 crontab
# 0 2 * * * /opt/enclave/scripts/backup.sh

# 手動觸發備份
./scripts/backup.sh

# 完整備份（含 schema + data + 壓縮）
./scripts/backup-full.sh
```

**備份保留策略：**
| 類型 | 保留期限 | 頻率 |
|------|---------|------|
| Daily | 7 天 | 每日 |
| Weekly | 4 週 | 每週日 |
| Monthly | 12 個月 | 每月 1 日 |

### 3.2 備份驗證

**每月執行一次：**

```bash
# 1. 還原備份到測試環境
./scripts/restore.sh backups/daily/enclave_20260207.sql.gz

# 2. 驗證資料完整性
psql -h testdb -d unihr_restore -c "
  SELECT 'tenants' AS tbl, COUNT(*) FROM tenants
  UNION ALL
  SELECT 'users', COUNT(*) FROM users
  UNION ALL
  SELECT 'documents', COUNT(*) FROM documents
  UNION ALL
  SELECT 'conversations', COUNT(*) FROM conversations;
"

# 3. 確認可正常查詢
# 4. 記錄驗證結果
```

### 3.3 Migration 執行

**標準流程：**

```bash
# 1. 在 Staging 先測試
docker compose exec web alembic upgrade head

# 2. 檢查 migration 狀態
docker compose exec web alembic current

# 3. 確認 Staging 正常後，在 Production 執行
# （由 CI/CD pipeline 自動處理）
```

**新增 Migration 時注意：**
- Migration 必須可逆（有 downgrade 函數）
- 避免長時間鎖表的操作（大表 ALTER 用 `CONCURRENTLY`）
- 先 `ADD COLUMN ... DEFAULT NULL`，後補 data migration
- CREATE INDEX 使用 `CONCURRENTLY` 避免鎖表

### 3.4 效能調優（定期）

**每月執行一次：**

```bash
# 執行效能分析腳本
./scripts/db-performance.sh

# 檢查項目：
# - 未使用的索引
# - Sequential Scan 比例過高的表
# - Dead Rows 過多的表（需 VACUUM）
# - Cache Hit Ratio < 99%
```

### 3.5 Vacuum 維護

```bash
# PostgreSQL autovacuum 通常足夠
# 但在大量刪除後可手動執行：

# 分析統計
docker compose exec db psql -U postgres -d unihr_saas -c "ANALYZE;"

# Vacuum（釋放空間）
docker compose exec db psql -U postgres -d unihr_saas -c "VACUUM ANALYZE;"

# 完整 Vacuum（重組表，會鎖表）— 僅在維護窗口執行
docker compose exec db psql -U postgres -d unihr_saas -c "VACUUM FULL ANALYZE auditlogs;"
```

---

## 4. 事故應對 SOP

### 4.1 事故分級

| 級別 | 定義 | 回應時間 | 例子 |
|------|------|---------|------|
| **P1 — Critical** | 服務完全中斷，所有用戶受影響 | 15 分鐘 | DB 掛了、API 全部 500 |
| **P2 — Major** | 核心功能受損，部分用戶受影響 | 30 分鐘 | 聊天功能失敗、文件上傳壞了 |
| **P3 — Minor** | 非核心功能異常，單一用戶受影響 | 4 小時 | 報表匯出錯誤、UI 顯示異常 |
| **P4 — Low** | 不影響使用，可計劃修復 | 下個 Sprint | 文件錯字、非關鍵 Bug |

### 4.2 P1 事故處理流程

```
0 min  ── 告警觸發 / 客戶反映
           │
           ▼
5 min  ── 值班人員確認事故
           ├── 判斷影響範圍
           ├── 初判嚴重等級
           └── 開始記錄事故時間線
           │
           ▼
15 min ── 啟動應變
           ├── 組建事故處理小組
           ├── 建立 War Room（Slack #incident-xxx）
           ├── 通知利害關係人
           └── 開始診斷
           │
           ▼
30 min ── 初步診斷
           ├── 查 Grafana 看指標異常
           ├── 查 Logs（structured logging）
           ├── 檢查 DB / Redis / Celery 狀態
           └── 識別根因
           │
           ▼
60 min ── 修復或緩解
           ├── 方案 A：回滾（最快）
           ├── 方案 B：Hotfix
           └── 方案 C：臨時緩解措施
           │
           ▼
       ── 確認恢復
           ├── 驗證服務正常
           ├── 通知客戶恢復
           └── 持續監控 2 小時
           │
           ▼
24-48h ── 事後檢討
           ├── 撰寫事故報告（Postmortem）
           ├── 識別根因（Root Cause）
           ├── 制定改善計畫
           └── 更新 SOP（如需要）
```

### 4.3 診斷命令速查

```bash
# ── 服務狀態 ──
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 web
docker compose -f docker-compose.prod.yml logs --tail=100 worker

# ── API 健康 ──
curl -s https://app.yourdomain.com/health | jq .
curl -s https://app.yourdomain.com/api/v1/admin/system/health \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq .

# ── 資料庫 ──
docker compose exec db psql -U postgres -d unihr_saas -c "
  SELECT state, COUNT(*) FROM pg_stat_activity GROUP BY state;
"
docker compose exec db psql -U postgres -d unihr_saas -c "
  SELECT query, state, age(now(), query_start)
  FROM pg_stat_activity
  WHERE state = 'active' AND query_start < now() - interval '30 seconds'
  ORDER BY query_start;
"

# ── Redis ──
docker compose exec redis redis-cli info clients
docker compose exec redis redis-cli info memory

# ── Celery ──
docker compose exec worker celery -A app.celery_app inspect active
docker compose exec worker celery -A app.celery_app inspect reserved

# ── 系統資源 ──
docker stats --no-stream
df -h
free -m

# ── Nginx ──
docker compose exec nginx nginx -t
tail -100 /var/log/nginx/error.log
```

### 4.4 常見事故處理指南

#### DB 連線池耗盡

**症狀：** API 大量 timeout，logs 出現 `QueuePool limit` 錯誤

**處理：**
```bash
# 1. 檢查活躍連線
docker compose exec db psql -U postgres -c "
  SELECT COUNT(*) FROM pg_stat_activity WHERE datname='unihr_saas';
"

# 2. 終止閒置連線
docker compose exec db psql -U postgres -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE datname = 'unihr_saas'
    AND state = 'idle'
    AND state_change < now() - interval '10 minutes';
"

# 3. 重啟 Web 服務（重建連線池）
docker compose restart web
```

#### Redis 記憶體不足

**症狀：** Rate limiter 失效，cache miss 率飆升

**處理：**
```bash
# 1. 檢查記憶體使用
docker compose exec redis redis-cli info memory

# 2. 清除過期 key
docker compose exec redis redis-cli --scan --pattern "rate_limit:*" | head -20

# 3. 如果是快取資料過多，清除可重建的快取
docker compose exec redis redis-cli FLUSHDB
```

#### Celery Worker 堆積

**症狀：** 文件上傳後狀態一直卡在 `processing`

**處理：**
```bash
# 1. 檢查佇列長度
docker compose exec redis redis-cli LLEN celery

# 2. 檢查 Worker 狀態
docker compose exec worker celery -A app.celery_app inspect active

# 3. 重啟 Worker
docker compose restart worker

# 4. 如有堆積，暫時增加 Worker
docker compose up -d --scale worker=3
```

### 4.5 事故報告模板

```markdown
# 事故報告 — [標題]

## 概要
- 事故編號: INC-YYYY-NNN
- 嚴重等級: P1 / P2 / P3
- 影響時間: YYYY-MM-DD HH:MM ~ HH:MM (共 X 分鐘)
- 影響範圍: 全部用戶 / 部分用戶 / 單一租戶
- 解決方式: 回滾 / Hotfix / 設定變更

## 時間線
- HH:MM — 告警觸發 / 客戶反映
- HH:MM — 值班人員確認
- HH:MM — 開始診斷
- HH:MM — 識別根因
- HH:MM — 實施修復
- HH:MM — 服務恢復

## 根因分析（Root Cause）
[詳細描述事故發生的技術原因]

## 影響評估
- 受影響租戶數: X
- 受影響用戶數: X
- 失敗請求數: X
- 資料遺失: 無 / 有（描述）

## 改善計畫
| 編號 | 行動項目 | 負責人 | 預計完成 |
|------|---------|--------|---------|
| 1    |         |        |         |
| 2    |         |        |         |

## 教訓
[此次事故的經驗教訓]
```

---

## 5. 值班與通知排程

### 5.1 值班制度

| 班次 | 時段 | 職責 |
|------|------|------|
| 日班 | 09:00 - 18:00 | 正常維運、部署、事故處理 |
| 夜班 On-Call | 18:00 - 09:00 | 接收告警、P1/P2 事故處理 |
| 週末 On-Call | 全天 | 接收告警、P1/P2 事故處理 |

### 5.2 通知管道

| 等級 | 通知方式 | 接收者 |
|------|---------|--------|
| P1 | 電話 + Slack + Email | 值班 + Tech Lead + PM |
| P2 | Slack + Email | 值班 + Tech Lead |
| P3 | Slack | 值班 |
| P4 | Ticket | 下個 Sprint |

### 5.3 告警規則

來自 Prometheus AlertManager：

| 告警 | 條件 | 等級 |
|------|------|------|
| ServiceDown | up == 0，持續 1 分鐘 | P1 |
| HighErrorRate | 5xx 率 > 5%，持續 5 分鐘 | P1 |
| HighLatency | P95 > 2 秒，持續 5 分鐘 | P2 |
| HighConcurrency | 並發 > 100，持續 2 分鐘 | P2 |
| DiskSpaceWarning | 磁碟使用 > 80% | P3 |
| DBConnectionHigh | 連線數 > 80% pool_size | P3 |

### 5.4 聯絡清單

```
# 此處應填寫實際聯絡資訊，以下為模板

Tech Lead:      [Name] — [Phone] — [Email]
Backend Dev:    [Name] — [Phone] — [Email]
DevOps:         [Name] — [Phone] — [Email]
PM:             [Name] — [Phone] — [Email]
DB Admin:       [Name] — [Phone] — [Email]
```

---

## 6. 日常運維檢查表

### 6.1 每日檢查（09:00）

- [ ] 檢查所有服務狀態：`docker compose ps`
- [ ] 確認 Health Endpoint：`curl /health`
- [ ] 檢查 Grafana Dashboard — 無異常告警
- [ ] 查看昨日 Error Log — 無異常增長
- [ ] 確認備份完成：`ls -la backups/daily/`
- [ ] 檢查磁碟空間：`df -h`

### 6.2 每週檢查（週一）

- [ ] 資料庫連線池使用統計
- [ ] Redis 記憶體使用趨勢
- [ ] Celery 佇列處理時間統計
- [ ] SSL 憑證到期檢查（< 30 天提醒）
- [ ] 依賴套件安全掃描：`pip-audit`
- [ ] Docker 映像安全掃描

### 6.3 每月檢查（1 日）

- [ ] 備份還原測試
- [ ] DB 效能分析：`./scripts/db-performance.sh`
- [ ] 清理過期 logs / backups
- [ ] 檢查各租戶配額使用率
- [ ] 更新系統套件 / Docker 映像
- [ ] 安全補丁確認

### 6.4 每季檢查

- [ ] 災難復原演練：`./scripts/disaster-recovery.sh`
- [ ] 負載測試：`locust -f tests/load/locustfile.py`
- [ ] 安全稽核：`./scripts/security-audit.sh`
- [ ] SOP 文件更新
- [ ] 備份策略檢討
- [ ] 成本優化檢討
