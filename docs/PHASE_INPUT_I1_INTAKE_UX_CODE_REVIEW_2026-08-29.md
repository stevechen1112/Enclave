# Input I1 — Intake Contract 與 UX 收斂 Code Review

日期：2026-08-29
結論：**PASS；Input I2 entry 開放。**
基準 commit：`d85b1503e1058ec4865d3f21a4477a363205c351`（本階段變更尚未 commit／部署）
資料庫 schema：無 migration；沿用既有 canonical Asset／Revision／IngestionJob schema。
Input contract：`input-capabilities.v1`，registry snapshot SHA-256 `90222a30392996f896b4d8bef0e37f79a2b8d13d0ee1583577ba7c24d2a4a30e`。

## 1. 審查範圍與結果

I1 已把「前端猜測後端能力」改為 server-owned capability contract。`/knowledge/new` 只開放目前部署環境可處理或明示降級的格式，並在送出前檢查格式、單檔與批次容量、空檔、影片時長、文件數量及租戶剩餘空間。Codec 由瀏覽器顯示政策、伺服器 probe 最終判定，沒有把本機無法證明的 codec 宣稱為已通過。

每個檔案建立固定 idempotency key；未完成草稿以 tenant-specific IndexedDB 保存。取消、頁面刷新或失敗重試會沿用相同 key。後端在文件、音訊與影片建立 canonical revision/job 前套用 classification、department ACL 及 allowlisted manufacturing context；同租戶相同 key 回傳既有資產，不同檔名、大小或來源 identity 則回 409。文件 worker 會沿用 intake key，不再建立另一個 job。

UI 已加入逐檔 checking／pending／uploading／done／error／cancelled 狀態、進度、可執行錯誤、取消、重試、批次共同治理 metadata，以及廠區、產線、設備、產品、工單、班別與標籤。Capability API 同時提供租戶文件／儲存配額與 provider runtime truth，畫面不再寫死「一定能 OCR／轉錄」。

## 2. Security、tenancy 與資料治理

- Capability discovery 必須登入，回應綁定目前 tenant identity。
- Department 必須屬於目前 tenant 且為 active；ACL 在 worker dispatch 前建立。
- Context metadata 採 allowlist、型別、項目數與 16 KiB 上限，不接受任意 JSON 欄位。
- Idempotency lookup 同時限制 tenant；跨租戶相同 key 不會相互命中。
- IndexedDB 以 tenant id 分庫，避免同一瀏覽器切換企業後看見另一租戶未完成檔案。
- Classification 支援 `public`、`internal`、`confidential`、`restricted`，由 capability policy 產生選項。

## 3. Reliability 與 failure semantics

- 重試在 quota／queue gate 前先解析既有 idempotent result，已接受的請求不會因後續滿額而失去可追蹤結果。
- 文件 canonical job 在 broker dispatch 前持久化；派送失敗會留下 failed job／asset／revision，而不是 silent loss 或只回未處理的 legacy row。
- 批次預檢會扣除已排隊檔案與本批前項的累積大小，避免每檔各自合法但整批超額。
- 前端 preflight error 不提供無效「重試」動作；使用者必須移除或更換檔案。傳輸／伺服器錯誤則可安全重試。
- 既有 URL identity 與檔案 replay 均保留 deduplication；檔案內容 checksum 仍由伺服器串流計算。

## 4. Code Review 發現與修正

審查期間關閉四項問題：

1. Unified route 原先沒有把 idempotency、department、classification 與 context 原子傳入 document/video canonical creation；已下沉到各 intake handler。
2. 前端最初只逐檔比較剩餘 storage，未計算整批累積；已改為 batch-aware preflight。
3. IndexedDB 草稿最初未以 tenant 隔離；已改為 tenant-specific database。
4. Document broker dispatch error 原先會在資產已 commit 後拋 500，留下不清楚狀態；已改為 persisted failed state，可從 asset retry 流程恢復。

最終 diff review 未發現未關閉的 P0／P1 correctness、tenant isolation、data loss 或 accessibility 問題。

## 5. 驗證證據

- Backend relevant regression：**105 passed／0 failed**。涵蓋 capability、sealed corpus、context validation、orchestrator、canonical assets、storage、video ingestion、document API/readiness/visibility 與 audio retention。
- Frontend Vitest：**32 files／110 tests passed**。
- Input I1 Playwright Chromium：**2 passed**。涵蓋 runtime capability-driven accept、oversize preflight、治理欄位、可執行錯誤及 Axe WCAG critical/serious = 0。
- TypeScript build、changed-file ESLint、Python compileall、`git diff --check`：PASS。
- Vite production build：PASS；Input page lazy chunk gzip 約 7.74 KiB。

關鍵 source SHA-256：

- `capabilities.py`: `6cda43ddea08df9405e8642b6ad8cb1c341bca2e6db63af0ba4463864eaeef5f`
- `input_capabilities.py`: `d6c80e8ba352529d226ec831642d52afc73b181b018bb7dd2d8113ac6c7c428c`
- `knowledge_assets.py`: `e0a79b7681ff410d105b793710c91c5228e95169705721e85cef8d56c198c292`
- `AddKnowledgePage.tsx`: `5799b3cf379659b4720b062bf780f9d73e6c2157bc2d95b6d4dd5b1e5b34d5cb`

## 6. 明示邊界與後續 gate

- `generic_resumable_upload=false` 維持真實狀態。I1 的 IndexedDB 是「草稿與 key 復原」，不是已確認 chunk 的斷點續傳；大型檔案弱網續傳必須在 I2 完成。
- Browser 無法可靠解析所有 codec，因此 client 只顯示允許政策；server probe 是權威拒絕點。
- 本階段 Chromium E2E 使用受控 API contract fixture；正式環境與實體手機／弱網／相機麥克風 campaign 仍屬 I2、I3、I5 與 I8 gate。
- 產品目前以繁體中文為正式 UI locale；I1 沒有新增多語系 framework。若產品啟用第二語系，需補 localization contract 與相同 E2E matrix。
- 本階段尚未部署；Production capability/UI parity 必須在正式部署流程另行驗證，不得用本文件宣稱 production 已更新。

依上述證據，Input I1 通過。下一階段只開放 Input I2「通用續傳與弱網可靠性」，不得把現有整檔重試描述成 resumable upload。
