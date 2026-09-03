# Input I9-7 擴大 Code Review：檢索、證據與正式環境

日期：2026-09-03

結論：PASS，准予部署檢索修補版；租戶內容仍須由租戶自行人工確認

## 生產檢查發現

1. 兩支 DJI 24-bit PCM WAV 在新版 Worker 上均完成正規化與轉寫，證明原始失敗不是檔案損壞。
2. WorkerLost 遺留的 JPEG 被 stale reconciliation 自動找回，完成 OCR、chunk 與 embedding。
3. 人工確認已由 140 筆不明數字改為來源與候選雙重計數；原 5 支影片為 138 筆候選。
4. 真實 Ask 雖可回應，第一次驗證沒有來源。追查確認不是 LLM 問題，而是第一方 URL 被 Connector ACL 誤分類；同時舊文件缺少後來新增的 lexical projection。
5. 檢索快取使用無密碼 Redis client，但正式 Redis 強制密碼，因此持續降級為無快取模式。
6. Gateway PEP 修正後仍無引用，第二層追查發現首租戶尚未建立 active KB revision；scope resolver 在 `shadow` 相容模式仍回傳 explicit empty scope，與 answer-ready 判定互相矛盾並關閉全部 legacy reads。

## 永久修正

- Connector ACL 現在只套用於 `Document.source_type == connector`。一般檔案、圖片與 URL Input 不會因 `source_system` 有值而被誤擋；canonical retriever 與 Gateway 的共同 visibility PEP 均使用同一分類規則。
- 外部 Connector 若無 principal／allow projection，仍維持 fail-closed；沒有放寬租戶或來源權限。
- Redis retrieval cache 使用執行環境的 `REDIS_PASSWORD`，不寫入程式碼、日誌或文件。
- lexical backfill 改用獨立 maintenance identity，跨租戶探索必須寫入 bypass audit，實際回填逐租戶套用 RLS context；另支援明確 `--tenant-id`。
- 八策既有 2 份完成文件、共 4 個 chunks 已冪等回填 lexical projection。
- 租戶尚未發布第一個 active KB revision 時，`shadow` 模式維持 legacy read compatibility；`enforce` 模式、明確指定 revision，以及已有 active revision但使用者無權存取時，仍 fail-closed。

## Review 檢核

- 安全：第一方來源修正不影響 `source_type=connector` 的 deny／allow 判斷。
- 多租戶：回填不以普通應用身分跨租戶讀取；探索與逐租戶操作分離。
- 可恢復：回填為 upsert，可重跑；原始來源、chunks 與 embeddings 不變。
- 資料語意：沒有替使用者核准任何音訊／影片候選。
- 測試：新增 canonical／Gateway 第一方 URL ACL、Redis 密碼、shadow compatibility 與 enforce fail-closed 回歸；I9 readiness／review focused suite共 11 passed，Python compileall 與 diff check 通過。
- 限制：本機 PostgreSQL `localhost:5435` 未啟動，因此 DB 整合由正式環境的實際 RLS、lexical 與 Ask 測試補足。

## 部署後 Gate

1. 正式 API、前端、Gateway、core worker、Input worker 全部 healthy。
2. Redis 不再記錄 retrieval-cache authentication warning。
3. 使用第一方網頁內容提問，回答必須至少帶 1 筆可追溯來源。
4. 李永仁可看到 9 個來源皆不再處於失敗／無限處理中；人工確認需清楚顯示來源數與候選數。
