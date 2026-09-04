# Input I10-0 可泛化解析品質稽核 — Code Review

日期：2026-09-04

結論：`PASS FOR I10-0 / PRODUCT QUALITY REMAINS HOLD`

## 1. Review 範圍

- `scripts/audit_asset_parse_quality.py`
- `tests/test_audit_asset_parse_quality.py`
- `artifacts/input/INPUT_I10_FIRST_TENANT_PARSE_QUALITY_AUDIT_2026-09-04.json`
- `docs/INPUT_I10_GENERALIZABLE_PARSE_QUALITY_ACCEPTANCE_PLAN_2026-09-04.md`
- `docs/INPUT_I9_FIRST_TENANT_PRODUCTION_HARDENING.md` 的第二輪追記

本 Review 只核准品質稽核基線及下一階段計畫，不代表 OCR、ASR、人工確認、發布或 Ask 缺陷已修復。

## 2. 泛化性檢查

| 檢查 | 結果 |
|---|---|
| 是否以租戶名稱或今日檔名決定品質 | PASS：執行時只接收 tenant UUID；來源由資料庫動態列舉 |
| 是否只檢查單一格式 | PASS：共通欄位外，按 artifact／requested capability 評估文件、圖片、音訊及影片 |
| 預期產物是否按檔名硬編碼 | PASS：依 ingestion job 的 requested capabilities 對應 artifact family |
| 是否能處理新租戶 | PASS：套用 tenant RLS context，沒有八策特定查詢條件 |
| 是否把 confidence 當真實準確率 | PASS：confidence 只作 triage；CER／WER 仍標示 NOT EVALUATED |
| 是否會修改正式資料 | PASS：程式沒有 insert、update、delete 或 commit，只輸出 JSON |
| 是否混淆處理完成與可問答 | PASS：receipt、processor、parse quality、review、publication／Ask 分開 Gate |
| 是否有反例與鄰近案例計畫 | PASS：S0–S3 分層資料集已列入 I10-1／I10-6 |

## 3. Correctness 與安全檢查

- 租戶 ID 使用 `UUID` 型別，進入查詢前套用 `apply_rls_context`。
- 僅列入 `tombstoned_at IS NULL` 的目前來源；不把歷史已刪除資料混入當前驗收。
- current revision 由 `SourceAsset.current_revision` 對應，不將舊版與新版混算。
- active published unit 必須同時通過 unit、revision、release membership 與 release status 條件。
- 未知 confidence、真正 0 與正分數分開計算；26 筆 zero sentinel 因而可被 Gate 捕捉。
- human-actionable evidence coverage 採 100% fail-closed；本次 121/122 因一筆缺定位而 FAIL。
- 程式在 blocking Gate 存在時回傳 exit code 2，便於未來接入 CI／release gate。正式遠端命令因此出現非零結束是預期結果，不是稽核程式崩潰。
- JSON 快照不包含原始檔或完整逐字稿，但含內部來源標題及 UUID，應依內部品質證據保存，不可公開散布。

## 4. 驗證結果

| 驗證 | 結果 |
|---|---|
| Python compile | PASS |
| Ruff | PASS |
| focused pytest | 3 passed |
| JSON parse | PASS |
| `git diff --check` | PASS；既有文件僅有 Windows CRLF 提示，無 whitespace error |
| 正式環境唯讀執行 | PASS：成功掃描 5 來源、153 artifacts、145 evidence spans |
| 快照 SHA-256 | `260e83bbc181cd958407eb95fdf525516591361768cd9000c0b9f7f83ccf02b5` |

## 5. 稽核揭露但未修復的阻擋項

1. `candidate_evidence_coverage`：一筆整合圖片文字缺 typed evidence。
2. `confidence_semantics`：26 筆影片逐字稿以 0 表示未知信心。
3. `ocr_quality_floor`：圖片 OCR 平均 52%。
4. `review_workload_design`：32 筆結構 artifact 進入人工佇列。
5. `semantic_accuracy`：沒有 ground truth，尚不能計算 CER／WER 或程序正確率。
6. `publication_and_ask`：本批為 0 決策、0 active unit，尚未執行。

## 6. Review 決議

I10-0 達成「建立可重跑、來源中立、租戶隔離的品質基線」目標，可以進入 I10-1。下一階段必須先建立 ground truth 與通用評分器；不能直接根據今天五筆調 prompt 或加檔名例外，也不能因收件與處理器 5/5 成功就把整體狀態改成 PASS。
