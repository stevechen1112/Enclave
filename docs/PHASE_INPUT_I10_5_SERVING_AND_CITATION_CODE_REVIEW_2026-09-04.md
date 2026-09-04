# Input I10-5 發布、Ask 與精確引用 Code Review

日期：2026-09-04
狀態：`PASS（程式與本機回歸）／待正式 E2E`

## 結論

2026-09-04 最終複檢補充：一般 Ask 在未明確選擇知識庫時，會納入租戶層級已發布的音訊、影片與圖片 Knowledge Units；使用者明確指定知識庫時仍維持嚴格 revision scope，避免跨知識庫污染。證據定位統一採毫秒，前後端深連結契約一致。

Ask 的 production default 已切為 Knowledge Authority `enforce`：只讀 active release membership，不再把 legacy completed document 當成已發布真相。一般公司級問答會同時查詢可存取的正式知識庫版本與租戶層已覆核多媒體單元；若使用者明確指定知識庫，範圍仍嚴格隔離。

## Review 發現與修正

1. 即使媒體 Knowledge Unit 已發布，一般 Ask 自動建立的 KB revision scope 原本會排除 tenant release，造成「已發布仍問不到」。現以明確 `include_tenant_knowledge_units` 契約只在未指定 KB 的公司級問答合併兩者。
2. Authority 中文查詢原本用空白切詞，繁中句子召回不可靠。現使用中文 2／3-gram、英文與代碼 token，標題加權並設 relevance floor；零支持或只有極弱泛用重疊不再附掛來源。
3. canonical 音訊／影片沒有 legacy `document_id` 時原本可能被判不可引用；現接受 immutable canonical resource／Knowledge Unit revision identity。
4. Citation contract 已涵蓋 page、section path、paragraph、slide、sheet／table／row／column／cell、bbox、start/end ms、speaker、frame 及 evidence URL。
5. 深連結曾同時存在「後端輸出秒、影片頁解讀毫秒」及「UUID evidence 被前端拒絕」兩個錯誤。現統一為毫秒，UUID 通過 allowlist，並攜帶 end、page、section、frame、bbox。
6. active source revision 仍有獨立高風險例外時，已核准的精確 artifact 可服務；沒有 exact artifact lineage 的單元仍要求整個 revision ready。

## 安全不變量

- 未發布、retired membership、tombstoned unit、撤權資產、跨租戶資產均不能讀取。
- 明確 KB scope 不會被 tenant-wide units 靜默放寬。
- 查不到可支持的 authority unit 時 sources 為空，不用語意相近但無關的 legacy 圖片裝飾拒答。
- 每筆 source link 由站內 route 與 query allowlist 驗證，不能導向外站。

## 驗證

- Authority／review／fusion focused regression：42 passed。
- Knowledge Authority release scope SQLite integration：PASS，覆蓋 strict KB 與 tenant-wide KB＋media 兩種行為。
- Evidence link Vitest 與 Review Queue Vitest：15 passed。
- Provider health contract：6 passed，probe 現包含 UTC 時間與完整 release identity；正式 CLI 對不可識別 release fail closed。
- 另 4 項 PostgreSQL 整合測試在本機因 pgvector extension 缺失無法執行；須由 release runner 補跑，不列為程式 PASS。

Critical／High 未處理 code finding：0。Phase 最終出口仍以 production publish → Ask → locator → revoke E2E 為準。
