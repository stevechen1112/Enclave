# Input I9-9 資產刪除與知識撤權 Code Review

日期：2026-09-03
範圍：統一資產庫刪除、相容 Document 投影、檢索與衍生知識撤權

## 結論

`PASS FOR DEPLOYMENT`。

修正後，刪除來源不再只是把 SourceAsset 從資產清單隱藏。若來源具有用於問答的相容 Document，系統會先呼叫既有 deny-first 文件撤權流程，再完成來源 tombstone 與工作取消。撤權失敗時回傳 HTTP 409，來源維持可見，避免產生使用者以為已刪除、AI 卻仍可檢索的危險狀態。

## Review 檢查

1. 查詢以 `tenant_id + source_asset_id + tombstoned_at IS NULL` 限制，只能操作目前租戶、目前來源的有效 Document。
2. 沿用共用 `DocumentRevocationService`，包含 Document tombstone、deny entry、retrieval cache invalidation、Wiki 與 knowledge graph tombstone；沒有建立第二套刪除邏輯。
3. 先撤銷知識投影，再隱藏 SourceAsset；失敗採 fail-closed，不會只完成 UI 層刪除。
4. 撤權服務可能 commit 並同步更新 SourceAsset，endpoint 會重新載入 canonical row，避免使用過期 ORM 狀態。
5. API 相容：原有 `asset_id` 與 `status` 不變，只新增不敏感的 `revoked_documents` 計數。
6. 原始檔仍依既有 tombstone／retention 政策保留，不會因本次修正意外硬刪。

## 驗證

- `tests/test_knowledge_assets.py`：9 passed，包含成功同步撤權與撤權失敗時 fail-closed。
- `tests/test_retrieval_facade_architecture.py`：17 passed。
- 合併 focused run：26 passed。
- 另執行 36 項較大回歸集合，其中 29 passed；7 項只因本機 PostgreSQL 測試服務 `localhost:5435` 未啟動而在 fixture setup error，沒有程式 assertion failure。
- `ruff check`：pass。
- `git diff --check`：pass。

## 部署後 Gate

1. 正式 API／Worker／Gateway 全部 healthy，restart 0、OOMKilled false。
2. 八策可見來源及人工確認清單維持 0。
3. 第一輪已撤權內容的 Ask 引用維持 0。
4. 正式 runtime 可載入新的刪除端點，且外部 Provider 及三條 Input queue guard 不受影響。

## 殘餘邊界

本修正保證「刪除一個來源」時知識投影同步撤權；它不等於硬刪儲存物件。實體檔案是否到期刪除仍由資料保留政策決定。李永仁第二輪真實檔案的內容品質、轉錄正確率與處理時間仍須由本輪租戶複測驗證。
