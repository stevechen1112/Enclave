# Input I9-5 Code Review：來源層級人工確認

日期：2026-09-03

結論：PASS，可進入 I9-6

## 變更範圍

- 人工確認 API 同時回傳來源群組與候選內容，明確分開 `source_total` 與 `total`。
- 核心 artifact 帶有穩定 `source_group_key` 與 `source_asset_id`；同一影片的逐字稿、OCR、程序候選會歸在同一來源。
- 工作台預設先呈現來源，再按需展開候選片段；不再把 138 個候選誤呈現為 138 個來源工作。
- 群組摘要顯示候選數、高風險數、低信心數及「需由另一位擁有者確認」。
- 候選層級的證據、風險確認、職責分離、核准與駁回規則維持 fail-closed。
- rolling deployment 相容：舊 API 沒有 `groups` 時，前端仍會依穩定 key 自行分組。

## Review 發現與修正

1. 最初 fallback 會把同來源的每個候選建立成重複群組；已改為 Map reducer，確實合併相同 source key。
2. 可選應用 provider 未必已有 source identity；為避免同名資料被錯誤合併，缺 key 時採一項一組的 fail-safe 行為。
3. 群組只改善瀏覽，不放寬批次核准：高風險、低信心、缺證據、職責分離或 SOP 衝突仍不可直接批次發布。
4. API 預設上限由 100 調為 500，確保八策目前 138 個影片候選能在同一來源群組完整呈現。

## 驗證證據

- `pytest -q tests/test_review_workspace.py tests/test_input_i9_review_grouping.py`：4 passed。
- `vitest src/pages/ReviewQueuePage.test.tsx`：4 passed。
- `tsc -b`：通過。
- `python -m compileall`：通過。

## 剩餘風險

- 單租戶超過 500 個同時待確認候選時，需要後續改為來源游標分頁；本輪 first-tenant corpus 未達此門檻。
- 李永仁是這批來源建立者，因此高風險內容應由陳宥竹確認；兩位皆為 owner 讓流程可完成，但權限不等於繞過職責分離。
