# Phase Application A4：生命週期與最終驗收 Code Review

**日期：** 2026-08-29
**結果：** PASS（程式與內部驗收）
**範圍：** tenant application install／enable／disable／archive／remove、舊管理路徑防繞過、跨應用與核心不回歸

## 1. 本階段完成內容

- 建立不可變 application lifecycle 狀態機：`absent → installed → enabled → disabled → archived → removed`，包含受控恢復路徑與 removed 終態。
- 新增 tenant-scoped `ApplicationLifecycleService`；沿用現有 `tenant_module_bindings` 作 entitlement authority，並在 versioned config envelope 保存 application key／version、操作者、時間、證據與 append-only transition history。
- 管理 API 新增 lifecycle 查詢，以及 install、enable、disable、archive、remove 操作。
- 舊 boolean binding API 與 ModuleRegistry enable／disable 已轉接至相同 lifecycle；archived／removed 不可由舊 API 重新啟用。
- MKA tenant eligibility 除 `enabled`／license／effective date 外，還會檢查 lifecycle state；即使舊程式或人工誤改欄位，也不能復活 removed application。
- 移除採 fail-closed：`export_then_delete` 應用必須同時提供 export receipt、`delete` disposition 及 disposition receipt；`retain_by_policy` 應用只能選 retain。
- 每次只改一個 module binding。測試證明移除報價不影響品質應用，且 Pack deployment、Workflow、Ask 與核心 query mode 不回歸。
- Lifecycle acceptance tests 納入 CI 架構 gate。

## 2. Code Review 發現與修正

### [Critical] 舊 enabled 欄位可繞過 removed 狀態

若 lifecycle 只寫 metadata，但 tenant eligibility 仍只看 `enabled=true`，舊管理 API 或人工 SQL 就可能重新打開已移除應用。現在 eligibility 必須同時符合 lifecycle `enabled`；有 metadata 的 archived／removed binding 即使欄位被改回 active，仍 fail closed。

### [High] 舊管理 API 直接修改 binding

Job module binding endpoint 與 ModuleRegistry 原本直接寫布林值，會跳過 transition history 與資料政策。兩者已改用 `set_enabled_compat()`；對 absent binding 自動 install，再 enable，對 archived／removed 回傳衝突。

### [High] 宣告 delete 不等於已刪除

初版 remove 只要求 `data_disposition=delete`，不足以證明資料處置完成。Code review 後增加 disposition receipt；沒有可稽核的匯出與刪除證明，不得轉成 removed。

### [Medium] 設定更新可能覆蓋 lifecycle metadata

舊 update-config 與 enable config merge 可能把 `_application_lifecycle` 整段洗掉。現在所有相容設定更新都保留該保護 envelope。

### [Medium] 一個應用的操作可能影響同 Pack 其他應用

驗收同時啟用報價與品質，停用、封存、移除報價後，品質 entitlement 仍維持 enabled；ApplicationManifest 與 module binding 是實際隔離單位，不以整個 MKA aggregate 一起切換。

## 3. 驗證結果

```text
application lifecycle／Pack runtime／module platform／job runtime
experience bootstrap／task engine／know-how lifecycle
Workflow boundaries／application boundaries／core query modes／P8 acceptance

134 passed
```

- Python compile：PASS。
- lifecycle state immutability 與非法轉移：PASS。
- disable／archive／remove fail closed：PASS。
- export／delete／retain evidence policy：PASS。
- legacy boolean revival attack：PASS。
- two-application coexistence and isolated removal：PASS。
- base-only deployment 已由既有 Pack deployment-off 測試證明 API、worker、UI contribution 全部消失，核心 registry 仍可組裝。
- `git diff --check`：PASS；只有 Windows LF／CRLF 提示。

## 4. 驗收邊界

- 本階段完成的是程式、API、權限與內部自動化驗收，尚未部署至 `kachu.tw`。
- 沒有改 UI 樣式；租戶管理前端目前仍以 enable／disable 為主，archive／remove API 已可用，但正式 UI 需要另行設計確認、證據提示與不可逆警告。
- disposition receipt 代表外部或應用專屬 purge/export executor 已完成資料處置；本共用 service 不會猜測每個應用有哪些資料表，也不會自行做跨域刪除。
- 四個應用仍由 frozen MKA package 配送，但租戶 entitlement、contract、資料政策與生命週期已分離。若要做到「在部署映像中物理刪掉單一應用程式碼」，仍需把四個 implementation directory 與前端 bundle 做純搬移；這不影響目前逐租戶停用／移除能力。
- 真實 production 資料 purge、回復演練與瀏覽器管理 UI 驗收未在本 Phase 假裝完成。

## 5. 最終決定

Phase A0–A4 的應用層脫鉤程式計畫全部通過。現在系統已具備穩定核心、共享 Workflow、版本化 ApplicationManifest、資料政策與租戶層可停用／封存／移除的安全邊界；後續場景應用可以逐一重新做產品驗證，而不必再改動 Input、Knowledge、Ask 或 Workflow 根基。
