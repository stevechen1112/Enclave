# Input I9-10 並行上傳 Deadlock 修復 Code Review

日期：2026-09-03

## 結論

`PASS FOR DEPLOYMENT`。

正式四格式並行上傳發現的 HTTP 500 已定位為 PostgreSQL tenant row lock upgrade deadlock。修正只改變 admission 序列化的 row-lock 強度，不放寬租戶上限、不改變 queue guard，也不改動 Input 內容與人工確認規則。

## 根因與修正

同一交易在呼叫 admission 前已建立 tenant-FK 的 SourceAsset／AssetRevision，因此持有 tenant row 的 `KEY SHARE`。多個並行交易再對該列執行 `FOR UPDATE` 時，會各自持有 KEY SHARE 並等待對方釋放，形成 deadlock。

改用 SQLAlchemy `with_for_update(key_share=True)`；PostgreSQL 實際 SQL 為 `FOR NO KEY UPDATE`。此鎖：

1. 仍與另一個 `FOR NO KEY UPDATE` 衝突，因此 admission 會依序執行，不會讓多個請求同時看見空位。
2. 不與外鍵檢查取得的 `KEY SHARE` 衝突，因此不需要危險的 lock upgrade。
3. 不改動既有 Redis 全域 queue 上限、租戶 active-job 上限及失敗回應契約。

## 測試與 Review

- SQL 編譯測試確認 admission lock 渲染為 `FOR NO KEY UPDATE`。
- 新增真實 PostgreSQL 雙交易測試；兩個交易各自先插入 FK asset／revision，再同步進入 admission，兩個 ingestion job 均成功 commit。
- 本機無 DB 測試：10 passed。
- candidate 隔離 PostgreSQL：28 passed，包含 orchestrator、I7 admission／fairness／recovery、P0 correctness 與資料生命週期。
- `ruff check`：pass。
- `git diff --check`：pass。

## 風險檢查

- `FOR NO KEY UPDATE` 是 PostgreSQL 專用語意；SQLite 單元測試會忽略 row lock，但另有 PostgreSQL 整合測試覆蓋真實行為。
- admission 仍為同租戶序列化，高量請求可能短暫等待，但應排隊成功而非隨機 HTTP 500。
- 本修正針對已重現的 tenant lock cycle；部署後必須重跑四格式同時上傳，並檢查 PostgreSQL 日誌不得再出現 deadlock。

## 部署 Gate

1. 四個並行來源全部 HTTP 202。
2. 文件到達 ready；圖片、24-bit WAV 與短影片到達 review_required，不得 failed。
3. 人工確認 API 依三個來源分組。
4. 文件 Ask 能回答唯一碼且附來源；刪除全部測試來源後再次 Ask 為 0 引用。
5. 八策最終可見來源 0、可見 Document 0、等待人工確認 0，兩位 Owner 保留。
6. 應用容器 restart 0、OOMKilled false，三條 queue 清空，部署後無新 deadlock、Traceback 或 WorkerLost。
