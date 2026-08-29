# Input I7 容量、成本與營運韌性 Code Review（2026-08-29）

結論：**INTERNAL CONTROL-PLANE PASS / LIVE CAPACITY GATE HOLD；僅准入 I8 Pilot 工具工程，不准入 GA、SLA 或容量承諾。**

## Review identity

- Baseline commit：`d85b1503e1058ec4865d3f21a4477a363205c351`，延續 I0–I6 dirty worktree，未部署生產。
- Schema head：`input_i7_operations_metrics_001`。
- P5 evidence status：`artifacts/input/i7_live_evidence_status.json` = `HOLD`。
- Authority：`config/capacity_profiles.json`、`docs/P5_CAPACITY_MODEL.md`、`app/services/capacity_gate.py`。

## 已完成工程控制

- Canonical `ensure_job` 在建立新工作前做 tenant row lock + per-tenant/global admission；idempotent replay 先返回既有工作，不會因 backlog 破壞重放。
- 每 profile 有有界 tenant active-job cap、global queue cap、media/day、jobs/hour、cost onboarding template；超限以 503 + Retry-After 回應，不丟失已保存來源。
- `fair_job_order` 以 tenant round-robin 選最舊 queued jobs，scan/output 都有硬上限；noisy tenant 無法佔用所有 admission slots。
- stale running job 在未達上限時可重排，達上限寫入 tenant-scoped DLQ；不刪 asset/revision。
- `InputOperationMetric` 以 tenant scope 保存 acknowledgement、transfer、queue wait、processing、review readiness；Prometheus 不使用 tenant label，避免高 cardinality 與租戶識別外洩。
- Operations API 提供 tenant dashboard、成本報告、容量估算、onboarding quota template 與手動 reconciliation。
- 既有 P5 runner/gate、global Redis backpressure、storage/cost guardrail 與 72h evidence integrity checks 保留。

## Review 發現與修正

1. **High — 新 metric table 的 schema probe 在 SQLite/同連線 transaction 會觸發 rollback。** 移除 runtime schema inspection；部署順序明定 migration-first，state transition 與 metric 保持同交易。
2. **High — I6 tenant-composite batch FK 的 ORM unique constraint 一度放在錯誤 table。** 移回 `ImportBatch(tenant_id,id)`；API fixture 與 PostgreSQL create/round-trip 重新驗證。
3. **High — admission 若只提供 dashboard 而未接 canonical job 建立，無法真正限制 backlog。** 接入 `IngestionOrchestrator.ensure_job`，並先處理 idempotent replay、再原子 admission。
4. **Medium — terminal metric 在 status 更新前記錄會被標為 pending。** 先設定 transition target status，再寫 phase metric與 event。
5. **Medium —只按全域 FIFO 無法證明 tenant fairness。** 增加有界 round-robin selector與 per-tenant admission；真正負載下的公平性仍由 live campaign 驗證。

## 驗證證據

- I7 + orchestrator + resumable upload + P5 queue/capacity/evidence/cost + DLQ：64 passed。
- Ruff（I7 Python、migration、tests）：PASS。
- `compileall app`：PASS。
- Alembic：隔離 PostgreSQL/pgvector fresh upgrade → downgrade I6 → re-upgrade I7：PASS，容器已移除。
- Existing P5 evidence validator 對目前缺少 live artifacts 的判定：`HOLD`，包含三 profile reports、四 degradation reports、cost live run 與 72h soak 缺失。

## Gate 與 waiver

- 無上限資源路徑：工程控制 PASS。
- Per-tenant admission／round-robin／DLQ／reconciliation：internal tests PASS。
- P0/P1 SLO live evidence：HOLD。
- 15 分鐘 2× profiles、四種 live degradation、72h soak：NOT RUN。
- 使用者先前明確要求先 pass 外部長測；此 waiver 只允許繼續 I8 Pilot 工具與流程工程，不把 I7 live gate 改寫為 PASS，也不允許容量/SLA/GA 宣稱。

因此 I7 Code Review 已完成；工程控制通過，但正式容量認證保持 HOLD。

## I8 獨立審查補強（2026-08-29）

I8 的跨階段 tenancy review 發現 `input_operation_metrics` migration 漏加資料庫層 RLS。此項被列為 P0 並在結案前修正：該表現在建立 `tenant_isolation` policy，且 `RLS_ENFORCEMENT_ENABLED=true` 時 FORCE RLS。隔離 pgvector/PostgreSQL 檢查確認 enabled、forced、policy present；I6–I8 相關 124 項回歸通過。I7 internal control-plane PASS 維持；live capacity gate 仍為 HOLD。

完整 1,511 項後端收集另發現 rolling deployment／精簡 schema 下，`input_operation_metrics` 尚不存在時 telemetry insert 會讓核心交易失敗。現已用 nested savepoint 隔離 metric write，失敗時告警但保留主交易，並新增專門回歸測試。最終完整結果為 1,499 passed／12 skipped／0 failed。
