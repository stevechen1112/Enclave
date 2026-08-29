# Phase Application A1：核心能力歸位 Code Review

**日期：** 2026-08-29
**結果：** PASS
**範圍：** Ask、規格／SOP 查詢模式、多模態 Input 邊界、Knowledge authority 的應用 entitlement

## 1. 本階段完成內容

- 建立核心 `KnowledgeQueryMode` contract；`spec_sop` 現在是 Ask 的核心模式。
- Chat API 新增 `knowledge_mode=spec_sop`；舊 `module_key=spec_sop` 只作相容轉譯。
- 前端 `/ask?mode=spec_sop` 送出核心 mode，不再送出 application module。
- `spec_sop` 從 MKA manifest、canonical module seed、相容性矩陣及職務預設模組移除。
- `ask` 從 MKA canonical TaskDefinition seed 移除，Task Engine 也會拒絕資料庫中殘留的舊 enabled row。
- MKA application module 從 5 個減為 4 個：報價、異常／交接、品質 8D、知識傳承／訓練。
- Knowledge authority 不再直接查詢 `TenantModuleBinding`；應用適用性改由通用 Pack owner 與 tenant eligibility resolver 判斷。
- Pack Registry 增加唯一 module owner 規則，禁止兩個 Pack 宣告相同 application module key。
- MKA 的長訪談能力改標示為 `application.knowledge_interview`；通用錄音、音訊、影片、轉錄與知識化仍由核心 Input／Knowledge 管線承擔。

## 2. Code Review 發現與修正

### [High] Knowledge authority 直接依賴 MKA binding

原本 active KnowledgeUnit 的 applicability 會直接 import `app.models.mka.TenantModuleBinding`。這讓核心知識讀取知道特定應用 ORM，也使未來新 Pack 無法使用同一治理規則。

修正後由 composition adapter 查找 module owner，再透過 `PackRegistry.is_enabled_for_tenant()` fail closed。核心 query mode 不需要 application entitlement。

### [High] 舊 enabled Ask task 可能在 production 繼續存在

只從 seed 移除 `ask` 無法處理既有正式資料。Task Engine 現在會在查詢 DB 前拒絕 legacy Ask task key；回歸測試刻意建立 enabled 舊資料，仍無法啟動。

### [Medium] 核心 mode 與應用 module 可同時送出

混合 scope 會造成檢索語意不明。`ChatRequest` 現在要求兩者互斥，只允許 `module_key=spec_sop` 與相同 mode 的舊相容組合。

### [Medium] Pack module owner 未保證唯一

Registry 原本只檢查 contribution key 與 UI route，兩個 Pack 仍可能宣告同一 module key。現在 composition 時直接拒絕重複 owner。

## 3. 驗證結果

Backend final regression：

```text
核心 query mode／application boundary／Pack runtime
experience bootstrap／capability catalog／module platform
module router／job runtime／task engine／knowledge authority
core capture／audio-video productization／video ingestion

198 passed
```

Frontend：

```text
TypeScript build check                         PASS
ChatPage + frontend module registry             12 passed
```

- Python compile：PASS。
- `git diff --check`：PASS；只有 Windows LF／CRLF 提示。
- 音訊切片、媒體 proxy、影片解流、時間碼、關鍵幀與 OCR 回歸：PASS。
- 未執行瀏覽器視覺驗收：本階段沒有畫面結構或樣式變更；新增的是 request scope contract。
- 未新增 migration：舊 `spec_sop` module／binding 資料保留供稽核與相容，但所有產品清單與 runtime 權威路徑均將它視為核心別名而非應用。

## 4. 相容與殘餘風險

- 歷史 migration 仍保留 `spec_sop` 字串，因 migration 必須不可變。
- 舊 `/ask?module=spec_sop` bookmark 可繼續使用，但會被正規化為核心 mode。
- 舊 DB module 與 binding 本階段不刪除；後續 A4 依資料生命週期封存。
- `app.models.mka` 仍承載 Task、Form、Approval 等共用 Workflow model，這是 A2 的主要工作，不在 A1 假裝完成。
- 知識訪談計畫仍是候選應用；通用錄音與媒體處理已證明不依賴它。

## 5. Gate 決定

Phase A1 通過，可以進入 A2。A2 只抽離共用 Workflow Kernel，不重設或擴充任何場景表單與流程。
