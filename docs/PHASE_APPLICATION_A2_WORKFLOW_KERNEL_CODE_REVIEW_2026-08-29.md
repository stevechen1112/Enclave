# Phase Application A2：Workflow Kernel 抽離 Code Review

**日期：** 2026-08-29
**結果：** PASS
**範圍：** Task、Form、Rule、Approval、Template 的共用模型、狀態契約、repository 與 API 所有權

## 1. 本階段完成內容

- 新增 domain-neutral `app.models.workflow`，正式承接 TaskDefinition、TaskRun、TaskRunEvent、FormDefinition、FormInstance、RuleSet、ApprovalPolicy、WorkflowApprovalRequest 與 FormTemplate。
- 保留既有資料表名稱及 foreign key，完成零 migration 的程式所有權移轉；`app.models.mka` 只保留舊 import 相容別名。
- 建立 `app.platform.workflow` 公開契約，集中管理 Workflow capability 與不可變 Task 狀態轉移。
- Task Engine、Task metrics、Form template service、共用 endpoints 與 MKA persistence 改用 Workflow model，不再以 MKA model 作為共用權威。
- Task、Form、Approval、Form Template routers 移至 base API 組裝；即使 MKA pack 未啟用，共用 Workflow surface 仍存在，但所有應用資料操作仍須通過租戶、角色與 module entitlement。
- 新增封閉的 `WorkflowRepository` 相容 facade。新共用 Form／Approval 程式只能使用明列方法，不能經由它建立或修改 know-how。
- Form definition 清單與新表單建立改為 fail closed：只顯示目前使用者可用應用所認領的 form key；沒有應用認領的表單不再因歷史相容而對所有人開放。
- CI 新增 Workflow Kernel ownership、import boundary、相容別名、router ownership、repository bridge 與狀態機測試。

## 2. Code Review 發現與修正

### [High] 共用表單 API 移出 MKA 後可能暴露未認領表單

原本 `assert_form_access()` 對「沒有 module 認領的表單」採開放策略。當 Forms router 成為 base product surface 後，這會讓租戶看見或建立殘留、停用或未正確註冊的表單。

已改為 fail closed。系統先計算目前使用者依 tenant、職能、部門與 enabled module 可用的 form key 聯集，list 與 create 都受同一規則限制；歷史 instance 仍依 owner／reviewer ACL 讀取，不靠開放新建權限維持相容。

### [High] 共用 ORM 仍由 `app.models.mka` 定義

Task、Form、Approval 若繼續由場景 aggregate 擁有，移除 MKA pack 就會破壞所有應用共同依賴的 workflow。實體定義已移至 `app.models.workflow`；舊 symbols 維持 object identity，只供逐步遷移，不產生第二套 metadata 或資料表。

### [Medium] Form／Approval endpoint 直接依賴大型 MKARepository

完整 MKARepository 同時提供 Workflow 與 know-how 方法，讓共用 API 可意外跨入應用資料。已新增最小化 WorkflowRepository facade，僅暴露 Form／Approval 方法；catalog 明列這是 A3 前唯一受控 persistence bridge。

### [Medium] Task 狀態機是 service 內可變字典

應用與共用服務若能各自修改狀態轉移，會產生不可預期流程。狀態契約已移至 platform workflow，以 read-only mapping 與 frozenset 暴露，並加入不可變測試。

### [Medium] 共用 handler 仍直接使用舊 repository

通用表單 handler 與報價 handler 已改走 WorkflowRepository。師傅訪談 handler 仍需建立 know-how，因此保留一處 lazy MKA persistence 依賴；它不是 Workflow 能力，列為 A3 將 handler 移入獨立應用註冊的明確阻斷項。

## 3. 驗證結果

Final backend regression：

```text
workflow kernel boundaries／application boundaries
product layer／job runtime／task engine／MKA persistence
P8 acceptance／Pack runtime／experience bootstrap／core query modes

171 passed
```

- Python compile：PASS。
- ORM table ownership 與 MKA compatibility alias identity：PASS。
- base API／MKA pack router ownership：PASS。
- 未認領 form fail-closed regression：PASS。
- `git diff --check`：PASS；只有 Windows LF／CRLF 提示。
- 未新增 migration；資料表歷史名稱刻意保留，避免本階段同時改變 schema authority。
- 未執行瀏覽器視覺驗收；本階段 public URL 不變，沒有畫面結構與樣式變更。

## 4. 相容與殘餘風險

- `mka_*` 歷史 table 名稱暫不更名；程式所有權已轉移，但 schema 命名會在確有價值且可零停機遷移時另案處理。
- `MKAApprovalRequest` 仍是 `WorkflowApprovalRequest` 的相容 symbol，不是第二個 model。
- `WorkflowRepository` 內部仍委派既有 MKARepository，因 approval 對 know-how 的歷史副作用尚待 A3 application hook；共用 endpoint 無法透過 facade 呼叫 know-how 方法。
- TaskEngine 仍含報價、異常、8D、訓練與訪談 handler；A2 只完成 Workflow Kernel 所有權，A3 必須把 application handler／definition／UI／API contribution 移入各自 manifest。
- Todo、Notification 與 Export 目前只有 domain-neutral capability contract；系統尚無由 MKA 擁有的通用 persistence model 可搬。未來新增時必須直接落在 Workflow Kernel，不得回到場景 pack。
- 固定表單 seed 仍會建立歷史相容 definitions，再於授權查詢時過濾；它不構成讀取權限，但 A3 應改為由各應用 manifest 註冊自己的 form definitions。

## 5. Gate 決定

Phase A2 通過，可以進入 A3。A3 的完成條件不是把 MKA aggregate 改名，而是讓每個應用透過 manifest 宣告所需平台能力，擁有自己的 handler、UI/API contribution 與資料生命週期；移除某個應用時不得影響 Workflow Kernel。
