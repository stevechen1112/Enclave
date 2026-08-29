# Phase Application A3：獨立應用契約 Code Review

**日期：** 2026-08-29
**結果：** PASS
**範圍：** Application manifest、平台能力依賴、資料政策、資源唯一所有權與 lifecycle 宣告

## 1. 本階段完成內容

- 新增不可變 `ApplicationManifest`；場景應用不再只是一個沒有完整語意的 module key。
- 每個應用必須宣告 semantic version、唯一 application／module key、自有能力、所需平台能力、task、handler、form、permission、資料政策與完整 lifecycle events。
- 新增 `ApplicationDataPolicy`，明確宣告停用、封存、移除與移除前匯出策略。
- `PackManifest.capability_keys` 現在只代表 Pack 自己提供的能力；新增 `required_platform_capability_keys` 表示它依賴的 Workflow 能力。
- Registry 在 composition 當下驗證未知平台能力、重複 application key、重複 module／task／handler owner、未宣告 permission 與 application／pack module 不一致，避免部署後才失敗。
- 四個既有應用已分別建立邏輯契約：`sales.quote`、`operations.incident_handover`、`quality.8d`、`training.knowhow`。
- Workflow UI 使用 `workflow.form`／`workflow.approval` 平台能力，不再把共用 Workflow 誤標成 MKA 自有 capability。
- Application contract 與 Pack runtime 測試納入 CI 架構 gate。

## 2. Code Review 發現與修正

### [High] Pack 把平台能力宣稱成自己的能力

MKA 原本把 `workflow.approval`、`workflow.fixed_form` 放在 `capability_keys`，導致移除 MKA 看起來會連 Workflow 一起消失。現在 MKA 只擁有報價、異常、品質與 know-how 能力；Task／Form／Approval 是它明確依賴的平台能力。

### [High] module key 沒有完整應用契約

只有 module key 無法回答版本、資料歸屬、停用後資料如何處理、有哪些 task／form／handler。新增 ApplicationManifest 後，任何 module 必須有對應契約，且 Pack 宣告的 module 集合必須完全一致。

### [High] 應用可宣告不存在的平台能力

這會讓部署表面成功，進入畫面才失敗。Registry 現在用 Workflow capability catalog 在 composition 時 fail fast；拼錯或不存在的 requirement 直接拒絕組裝。

### [Medium] task／handler 可能被兩個應用同時宣稱

Registry 已加入 application resource owner 唯一性檢查。四個現有應用各自擁有其 task 與 handler key，後續新 Pack 無法重複註冊。

### [Medium] 應用沒有移除前資料決策

ApplicationDataPolicy 現在是必填。報價、異常、品質採 `export_then_delete`；知識傳承採 `retain_by_policy`，反映正式知識與稽核資料不應隨 UI 停用直接刪除。

## 3. 驗證結果

```text
Pack runtime／application boundaries／experience bootstrap
Workflow boundaries／product layer／job runtime／task engine

138 passed
```

- Python compile：PASS。
- Application manifest immutability、完整 lifecycle 與 data policy：PASS。
- application／module／task／handler owner uniqueness：PASS。
- unknown platform capability fail-fast：PASS。
- 未變更資料庫 schema、public URL 或 UI 樣式。

## 4. 邊界說明

- 四個既有應用目前仍由同一個已凍結的 MKA deployable package 配送，但 Registry 已將它們視為四個獨立、可逐租戶授權的 application contract；這是保留正式站相容性的刻意過渡。
- 共用 Task／Form／Approval API 與畫面屬 Workflow Kernel，應用透過 task／form definition 使用，不需要複製一套專屬 CRUD UI 才算獨立。
- 舊 TaskEngine 的 handler 實作位置仍是相容宿主；A3 已建立唯一邏輯 owner 並禁止新應用沿用大型 MKA seed。將既有四個 handler 搬成四個 physical package 是後續可獨立排程的零行為搬移，不阻擋租戶層生命週期驗證。
- A3 不宣稱資料已可直接物理刪除；A4 必須證明 disable／archive／remove 的 runtime 行為與匯出／資料處置前置條件。

## 5. Gate 決定

Phase A3 通過，可以進入 A4。A4 將以租戶為單位驗證應用生命週期；任何狀態都不得影響 Input、Knowledge、Ask、Evidence 或 Workflow base surface。
