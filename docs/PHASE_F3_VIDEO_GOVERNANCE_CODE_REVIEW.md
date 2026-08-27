# Phase F3 Code Review：結構化程序、SOP 衝突與發布治理

**Review date**: 2026-08-26
**Gate result**: PASS（完成下列修正後）

## Review 範圍

- 以原始 EvidenceSpan 分類步驟、前置條件、判斷規則、風險、例外、禁止動作。
- 適用機台/角色 metadata、asset revision 與生效期間投影。
- 租戶當前 completed SOP 文件版本、chunk 證據與 Authority Tier 衝突檢查。
- 未解決衝突、高風險確認、review decision 與 SOP-wins 發布投影。
- 核心檢索只讀 approved decision 中的 governed projection，不讀未處置候選。

## 發現與修正

1. **[Critical] 核准 artifact 後若仍檢索原候選，SOP-wins 只是 UI 標記**
   - 修正：review decision 儲存 immutable `published_procedure`；provider 必須 join approved decision 並只輸出已套用正式 SOP 的投影。
2. **[High] 衝突報告只到 SOP 檔名，無法找回實際條文**
   - 修正：每個 conflict 加入 document id/revision/chunk id/index，UI 可直接開啟正式來源。
3. **[High] 語意去重把 transcript 與 action artifact 當成同一物，會遺失 action lineage**
   - 修正：artifact-kind 層保留衍生系譜，只在分類顯示層去除同文同時間的重複。
4. **[High] HR 角色預設可核准高風險機台程序**
   - 修正：核心後端與 UI 一致收旂為 owner/admin/superuser；後續可以租戶審核能力取代角色常數。
5. **[High] 無語音且無 OCR 的影片會永久卡在 human_review**
   - 修正：無證據候選時工作以 `completed_no_knowledge` 結案、`searchable=false`，不製造空的審核任務。
6. **[High] 高風險候選可能與普通步驟用相同核准請求**
   - 修正：API 需要 explicit acknowledgement，並將確認寫入 review decision；未確認回 409。
7. **[Medium] 過度寬鬆的「安全」關鍵字把正常的安全門名稱標成風險**
   - 修正：移除單獨「安全」，只在具體風險/注意/傷害/禁止語詞出現時分類。
8. **[Medium] 客戶端可送入不屬於報告的虛假 conflict id**
   - 修正：核准 API 比對 report id set，額外 id 回 400，漏處置 id 回 409。

## 發布不變式

- 原始影片、候選 procedure 與 conflict report 保持 immutable lineage。
- 任一未處置衝突不得核准；唯一自動處置語意是 `sop_wins`。
- 高風險必須有主管級角色與明示確認。
- 低信心內容永遠是 `review_required`，沒有自動核准路徑。
- retrieval provider 必須同時看到 ready artifact、approved review decision、active/non-tombstoned video asset。

## 驗證證據

- Phase F 專屬測試：21 passed，含證據分類、衝突阻擋、SOP-wins 檢索投影、高風險確認、無候選結案、聲學離群不診斷。
- Asset/Ingestion/Knowledge/Retrieval 相關回歸：61 passed。
- Frontend：69 passed；production build 與 ESLint 通過。
- PostgreSQL：F3 downgrade/upgrade 往返與 `alembic check` 通過。
