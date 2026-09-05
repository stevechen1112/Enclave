# 第一租戶修復保留性 Code Review

日期：2026-09-05

範圍：李永仁數輪測試所揭露的 Input、Knowledge、Review、Ask 共用核心

判定：`PASS FOR DEPLOYMENT CANDIDATE`

## 1. 結論

先前已部署的主要修復仍存在於正式 source commit `e2cc7490217c689343d6cc8aec7890288d31d8f2`，且該版本包含 Reality Audit 修復 commit `8c7c949f0ff230c7c3aebfc6962cf1ed1c6fe072`。本次沒有發現 WAV 支援、Worker 復原、單一狀態真相、人工確認簡化、檢索、證據引用、租戶權限或刪除撤權被後續媒體工程回退。

本次發現並修正兩項 candidate 缺口：

1. 證據定位修復已正確讓整份來源與實際片段各有 EvidenceSpan，但舊測試仍要求全表只能有一筆，造成五個假失敗。
2. I9-012 尚未真正完成：文件與影片缺少一致的內容雜湊去重，並行重送仍可能產生兩個來源，影片統一 API 也可能錯誤回報未去重。

## 2. 審查與修正內容

### 2.1 證據定位契約

- 保留 parent `extracted_text` 與 child chunk 各自的精確定位，讓來源層級確認與片段引用都可追溯。
- 測試改為驗證兩種 artifact 都有正確 locator。
- 同一 projection 重跑後 EvidenceSpan 數量不得增加。

### 2.2 跨格式內容去重

- 文件、音檔、影片統一使用 SHA-256 內容身分。
- 去重範圍限定同租戶、同資產種類、同資料分級、同部門 ACL、同 Input context，且目前使用者必須有權存取既有來源。
- 相同檔案若使用不同資料分級或治理 context，不會被錯誤合併。
- tombstone 來源不會復活或被當作重送結果。
- 命中既有來源時回傳同一 asset id、`deduplicated=true`、不重複派送、不重複進行成本與儲存預留。
- PostgreSQL transaction advisory lock 防止同租戶同內容的並行 read-before-create race。
- 文件 legacy row、canonical asset、revision、job 與 outbox 改為同一 transaction 建立。

### 2.3 容量與失敗清理

- 內容去重在 queue capacity、配額、媒體 probe、成本預留與物件儲存前完成。
- queue 或配額 Gate 拒絕時清除本機暫存檔。
- 不改變不同租戶、不同 ACL、不同資料分級與不同 context 的合法獨立資產語意。

## 3. 驗證結果

| Gate | 結果 |
|---|---:|
| Input／Review／Retrieval／Authority／Evidence／Document／Video／Security focused backend | 202/202 PASS |
| 去重、證據與 PostgreSQL advisory lock 核心組合 | 57/57 PASS |
| 文件真實 API 重送 | 同一 document/source id，清單僅一筆 |
| 音檔重送 | 同一 asset/revision，只派送一次 |
| 影片重送 | 同一 asset/revision，`deduplicated=true`，不派送 |
| 不同資料分級的相同內容 | 保留兩個獨立邏輯資產 |
| PostgreSQL 同內容並行鎖 | 第二交易等待第一交易結束後才繼續 |
| 前端 Input／Asset／Review／Evidence | 24/24 PASS |
| Ruff／format／diff check | PASS |
| ESLint／TypeScript／production build | PASS |

測試期間曾有五項舊 vertical-slice 測試連到預設 `localhost:5432/enclave` 而失敗；改以隔離 pgvector 測試資料庫的正確環境設定重跑後為 16/16 PASS。此項是測試啟動環境問題，不是產品行為失敗。

## 4. 尚未完成的證據

- Candidate 尚未部署至正式環境，因此 I9-012／I9-026 現在只能標記 `FIXED_IN_CODE`。
- 部署後必須在正式網域驗證：同檔循序重送、同檔並行重送、不同資料分級不合併、原來源 tombstone 後可重新上傳。
- 李永仁仍需用真實內容完成 Input → 人工確認 → 發布 → Ask 引用，才能關閉租戶旅程。
- 音訊、圖片與影片語意準確率仍須獨立人工真值；本次 Code Review 不把流程正確誤當成內容品質已認證。

## 5. 發布判定

目前 candidate 沒有未處理的 Code Review blocker，可以進入正式部署 Gate。正式部署及租戶複測完成前，不宣稱問題已全面 `CLOSED`。
