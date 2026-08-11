# Phase 8 驗收清單（職能任務平台重構）

日期：2026-08-07

## 已由程式驗證（自動化）

| 項目 | 驗證方式 | 狀態 |
|---|---|---|
| 報價垂直切片全鏈路（語音/文字 → 知識補值 → 規則計算 → 送審 → 匯出守衛） | `tests/test_p8_acceptance.py::TestQuoteEndToEnd` | ✅ |
| 第二租戶隔離（opt-in、覆寫不外洩、run 隔離） | `tests/test_p8_acceptance.py::TestSecondTenantIsolation` | ✅ |
| 任務層角色 ACL 矩陣（能力 + 職能雙重把關） | `tests/test_p8_acceptance.py::TestTaskRoleACLMatrix` | ✅ |
| 能力雙軌一致性（前後端 ROLE_CAPS parity） | `tests/test_capability_parity.py` | ✅ |
| 既有 28 項 MKA 閘門（含真實 DB 的 E2E、retrieval Z-score） | `scripts/mka_progress_gate.py --all` | ✅ 28/28 |
| 後端全量回歸 | `pytest tests/` | ✅ 918 passed |
| 前端型別與快照 | `tsc -b` + `vitest run` | ✅ 38 passed |

## 需要真實環境驗收（程式無法代驗）

| 項目 | 缺什麼 | 建議做法 |
|---|---|---|
| 真語音端到端（麥克風 → STT → 欄位帶入） | 正式語音 provider 金鑰與額度；本機測試曾遇 provider error | 在 staging 設定正式 provider，用三支 demo 劇本各錄一次真實語音，確認 `detected_fields` 帶入與信心分數顯示 |
| Hold-out 語音集 | 標註過的真實現場語音樣本 | 收集 ≥ 20 段現場錄音，跑 STT 字錯率與欄位抽取準確率，門檻訂入 gate |
| 真人 UX 驗收 | 真實使用者（業務／現場／品保各 1 人） | 依 `docs/baselines/BASELINE_2026-08-07.md` 三劇本操作 TaskWorkspace，記錄完成率與手動修改率（對照 `/tasks/metrics/summary`） |
| 漸進上線 | 正式環境發佈窗口 | 依 `docs/runbooks/STAGING_AND_ROLLBACK.md`：先單一租戶（Demo Tenant）啟用模組 binding，觀察指標一週後再開第二租戶 |

## 上線前檢查

1. `python scripts/mka_progress_gate.py --all` 全綠。
2. `bash scripts/db_backup.sh` 產出上線前備份。
3. `bash scripts/migration_dryrun.sh` 確認 migration SQL 無意外（本次新增 `mka_task_definitions`、`mka_task_runs`、`mka_task_run_events` 三表與三個新欄位）。
4. 新租戶開通流程：建租戶 → 管理員至「系統 → 租戶設定 → 模組設定」逐個 opt-in → 建立職能並指派使用者。
