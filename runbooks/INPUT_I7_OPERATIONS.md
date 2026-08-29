# Input I7 營運操作手冊

## 上線前順序

1. 先執行 Alembic 到 `input_i7_operations_metrics_001`，再更新 API/worker；Input phase metrics 是 state transition 的同交易證據。
2. 設定 `DEPLOYMENT_PROFILE`，確認 `/api/v1/operations/input/dashboard` 顯示正確 profile、tenant admission、成本與 SLO evidence state。
3. 用 `/api/v1/operations/input/capacity-estimate` 建立 onboarding 初始配額；輸出只供規劃，不是 SLA。
4. 確認 Redis global queue guard、tenant active-job cap、storage/cost quota 與 `Retry-After` 皆可觀測。

## Backpressure 與公平性

- Global queue 飽和時，Input API 回 503 `queue_saturated`，來源尚未接受並提供 `Retry-After`。
- Tenant active-job cap 在 canonical ingestion job 建立前，以 tenant row lock 原子檢查；重放既有 idempotency key 不會被誤擋。
- `fair_job_order` 以各 tenant 最舊工作 round-robin 選取，掃描與輸出都有硬上限；worker 預取應維持 1，避免單 worker 預抓大量 noisy-tenant 工作。
- 任何 profile 數字是內部驗證起點；沒有對應 live report 不可成為對客承諾。

## Reconciliation／DLQ

- 租戶管理者可呼叫 `POST /api/v1/operations/input/reconcile?stale_minutes=60`。
- 未達 retry 上限的 stale running job 轉回 queued 並留下 event；已達上限則 failed 並寫入 tenant-scoped `DeadLetterEvent`。
- DLQ 不刪來源 asset/revision；修復 provider 或資料後應以原 idempotency/lineage 重試，不可建立無關的新來源。

## SLO 與成本

- SLO phases：acknowledgement、transfer、queue_wait、processing、review_readiness。
- Prometheus labels 只用固定 journey/phase/outcome，不含 tenant ID；tenant 明細保存在 RLS 資料表。
- 成本儀表板呈現 storage GB-month、audio hour、video hour、query units 與 guardrail state。
- Dashboard `NOT_MEASURED` 是正常且必須保留的狀態，不能用 synthetic unit tests 改成 LIVE。

## 正式 live campaign

依 `docs/P5_CAPACITY_MODEL.md` 執行隔離 staging：Lite/Standard/Enterprise 各至少 15 分鐘 2× peak、四種 degradation drill、成本護欄，以及 Standard 72 小時 soak。最後以 `scripts/verify_p5_capacity.py` 獨立驗證；只有輸出 `PASS` 才能宣稱容量與 SLA gate 通過。
