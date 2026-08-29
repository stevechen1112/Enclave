# 第四、五、六層現況盤點：Workflow、Domain Pack、Tenant Solution

**日期：** 2026-08-29  
**適用版本：** production `production-ask-315d23d`  
**目的：** 說明目前系統已經有哪些第四、五、六層能力，以及哪些仍是架構目標，避免把設計藍圖誤當成既有產品功能。

---

## 先講結論

目前產品的前三層（多租戶治理、企業知識核心、多模態 Input）是共同地基。第四到第六層已有可用實作，但成熟度不同：

| 層級 | 現況 | 白話結論 |
|---|---|---|
| 第四層：Workflow Kernel | **部分平台化、可實際運作** | 任務、表單、簽核、情境、語音互動與稽核能力已存在；目前主要由 MKA 使用，尚未完全抽成獨立、通用的流程產品。 |
| 第五層：Domain Packs | **已建立 Pack Runtime；目前一個 Pack** | MKA 是唯一已實作、可部署、可依租戶啟停的製造業應用包。 |
| 第六層：Tenant Solutions | **設定式能力已具備；專屬方案仍需交付設計** | 可依租戶啟用模組、配置職能、表單、詞典、情境、規則與簽核；尚非無限自由的低碼客製平台。 |

最重要的現況是：**MKA 已不再是核心平台的硬依賴，但第四層的許多成熟實作仍位於 MKA 的邊界內。** 這是合理的第一階段做法，但未來若有第二、第三個 Pack，應持續把真正共通的能力抽回 Workflow Kernel。

```text
多租戶、知識、Input
        ↓
Workflow primitives（目前多由 MKA 首先使用）
        ↓
MKA Pack（目前唯一可部署 Domain Pack）
        ↓
每個租戶的 binding、角色、設定、模板與整合
```

---

## 第四層：Workflow Kernel 現有什麼

第四層的責任是讓「查到知識」後，能變成一個可執行、可追蹤、可覆核的工作。它不應自行理解 8D、報價或維修的業務語意；它提供的是任務、表單、規則、簽核與稽核等共通機制。

### 1. 任務引擎：定義、執行、狀態與事件

目前已有版本化任務定義、任務執行紀錄與事件流：

- `TaskDefinition`：任務名稱、版本、所屬模組、輸入 Schema、適用職能、所需能力、風險等級、輸出綁定與簽核政策。
- `TaskRun`：一次實際執行的任務，保留輸入快照、執行時職能／情境、欄位來源、provenance、錯誤與輸出參照。
- `TaskRunEvent`：建立、欄位更新、人工修改、狀態轉換、執行或失敗的事件紀錄。
- `TaskEngine`：租戶覆寫優先、全域 fallback、版本解析、權限檢查、idempotency 與 typed handler 呼叫。

目前統一狀態機為：

```text
draft
→ in_progress
→ waiting_review
→ approved / rejected
→ executed / exported / failed
```

未實作的 handler 會明確失敗，不會假裝任務已完成。任務啟動時同時檢查：使用者能力、租戶啟用的模組、職能 allowlist 與場景限制。

### 2. 表單與輸出模板

目前已有固定表單與可版本化輸出模板：

- `FormDefinition`：欄位 JSON Schema、UI Schema、必填規則、欄位來源、輸出格式、規則集與簽核政策。
- `FormInstance`：實際填寫資料、欄位 provenance、計算快照、驗證結果、場景脈絡、來源文件與 optimistic locking。
- `FormTemplate`：租戶自己的 DOCX／XLSX 模板、placeholder、欄位 mapping、版本、啟用日與取代關係。
- 表單可由手動輸入、語音、掃碼情境、規則、ERP 資料或知識結果填入；每個欄位可保留來源。

這代表系統已不只會「回答」，也能把資料組成公司使用的表單或匯出格式。

### 3. 規則與簽核

目前已有的規則與簽核資料能力包括：

- `RuleSet`：資料模型與 Schema 可保存價格、稅、MOQ、交期等規則的輸入／輸出、實作參照與測試案例；目前沒有完整的通用規則管理 API／UI，不能視為已完成的低碼規則引擎。
- `ApprovalPolicy`：可管理適用物件、風險等級與多級簽核步驟；逾時與代理政策目前可保存及編輯，但尚未證明所有政策都有完整的自動排程／代理執行。
- `MKAApprovalRequest`：送審人、當前關卡、決策紀錄、idempotency key、到期日與核准後 immutable snapshot。
- 簽核狀態機：避免未經核准的表單、知識卡或高風險操作直接視為正式結果。

這些能力是未來「AI 協助填寫，但人類保有決策權」的關鍵安全邊界。

### 4. 語音、掃碼與現場情境

目前 Workflow 已可使用現場輸入，不只接受網頁文字：

- `InteractionSession`：文字／語音／掃碼跨步驟互動、逐字稿、偵測欄位、待補問題、風險與確認狀態。
- `SceneRegistry`：QR token 對應到廠區、產線、設備、工單、產品、料號、客戶與文件版本範圍。
- `JobRole` 與 `UserJobRoleAssignment`：把「安全角色」以外的實際工作職能，例如業務、設備現場、班長、主管、新人，帶入任務解析。

白話來說，使用者掃一台設備的 QR code 後，系統可以在建立任務或查詢知識時，自動帶入「哪個廠、哪條線、哪台設備、哪張工單」；但仍必須受租戶、角色、模組與知識權限限制。

### 5. 稽核、成本與寫入護欄

現行能力還包括：

- 任務事件、表單版本、簽核決策與欄位來源的稽核資料。
- MKA 背景工作成本紀錄，例如語音辨識、LLM、embedding、OCR、rerank 與儲存。
- 對外寫入與高風險 action 的 approval／rollback audit 邊界。
- 背景任務、可重試處理與失敗顯性化。

### 第四層目前的界線

第四層**不是**完整的通用 BPMN／低碼流程引擎，也不是每個新流程都能零開發拖拉完成。目前最成熟的任務、表單、簽核資料模型仍在 `mka_*` 表與 MKA API 中；規則、逾時、代理與通知也不能僅因已有欄位或局部服務，就推定為完整的通用 workflow automation。

因此現況應表述為：

> 已有可工作的 workflow primitives 與狀態機；它們已能支撐 MKA，但尚未完全收斂為任何未來 Pack 都可直接採用的獨立 Workflow Product API。

未來新增第二個 Pack 時，若發現其也需要任務、表單、簽核、場景或輸出能力，就應抽取契約與服務，而不是複製 MKA 程式碼。

---

## 第五層：Domain Packs 現有什麼

第五層是職能／場景產品模組。它把第四層的共通能力與前三層的知識能力，組合成使用者看得懂、能每天使用的工作工具。

### Pack Runtime 已具備的機制

目前的 Pack Runtime 可讓一個 Pack 以 manifest 宣告並掛載：

- pack key、版本、顯示名稱、擁有團隊與穩定性。
- 所需 deployment capability。
- module key、permission key 與 tenant eligibility。
- Knowledge Provider／Projector。
- API router、Celery task handler、review provider、lifecycle hook。
- 前端 route、navigation、workspace manifest 與 default home。

一個 Pack 真正對某人可用，必須同時滿足：

```text
部署能力可用
AND 租戶已啟用／授權
AND 目前使用者有權限
AND 執行環境健康
```

停用時必須 fail-closed：API、背景工作、檢索來源、導航、路由與可操作 action 都不應殘留半開狀態。

### 已實作的第一個 Pack：MKA

目前唯一已實作並納入 composition root 的 Domain Pack 為：

```text
MKA — Manufacturing Knowledge Applications
版本：1.0.0
定位：beta
```

MKA 目前定義五個職能模組：

| 模組 key | 白話用途 | 現有能力例子 |
|---|---|---|
| `spec_sop` | 規格與 SOP | 知識查詢、設備／場景範圍限定、正式文件引用。 |
| `sales_quote` | 報價與產銷協作 | 語音或表單蒐集欄位、規則、輸出與簽核入口。 |
| `incident_handover` | 異常與交接班 | 異常回報、交班內容、任務與現場脈絡。 |
| `quality_8d` | 品質改善 | 客訴、圍堵、根因、矯正、驗證、簽核與 8D 類型流程。 |
| `training_knowhow` | 師傅傳承與訓練 | 訪談／長音檔、知識卡、覆核、適用設備與新人學習。 |

目前另有八個已啟用的全域任務定義，由租戶模組綁定、職能與能力共同決定使用者是否看得到、能否啟動：

| 任務 key | 任務名稱 | 所屬模組 |
|---|---|---|
| `ask` | 問知識庫 | `spec_sop` |
| `quote` | 開報價單 | `sales_quote` |
| `incident` | 異常回報 | `incident_handover` |
| `handover` | 交接班紀錄 | `incident_handover` |
| `daily_report` | 工作日報 | `incident_handover` |
| `quality_8d` | 品質 8D 報告 | `quality_8d` |
| `interview` | 師傅訪談 | `training_knowhow` |
| `training` | 新人訓練 | `training_knowhow` |

這些是正式任務定義與執行骨架，不代表每一個模組都已完成相同深度的客戶現場驗收、產業模板與商用成熟度。

MKA 也實際掛載了：

- `/job` 現場作業工作台與動態職能入口。
- forms、form templates、tasks、approvals、job roles、job modules 等 API。
- knowhow、interview、長音檔／語音擷取、術語與場景 API。
- 已核准師傅經驗的知識 provider 與跨來源 review provider。
- 租戶建立後的 Pack lifecycle provision hook。

### 不應誤認為已完成的 Pack

目前並沒有已成熟、獨立部署的「品保 Pack」、「維修 Pack」、「HR Pack」或「ERP Pack」。它們是未來可能從 MKA 模組拆出或新建的方向。

程式中可見的 `knowledge_compiler`、`agent_automation` 等相容或能力矩陣名稱，不應直接對外宣稱為可售、可獨立啟用的產品 Pack；現況唯一可確認的可部署 Pack 是 MKA。

---

## 第六層：Tenant Solutions 現有什麼

第六層的目標是讓同一套平台與 Pack，不同企業可以有不同流程、詞彙、職能與版型，而不必 fork 核心程式。

### 1. 模組綁定與啟停

`TenantModuleBinding` 已提供每個租戶的模組控制：

- 模組是否啟用。
- 試用、有效、過期、停用等 license state。
- 生效與到期時間。
- `config_json` 租戶覆寫設定與 `config_version`。
- 同一租戶不同模組可個別控制。

一般新租戶採 opt-in：如果沒有任何已啟用 binding，就不會看到全域 MKA 模組。只有受控 seeder 或明確帶入 `enable_default_modules` 的 provisioning 流程才會一次建立預設啟用綁定；這不應描述成所有新租戶自動開啟全部 MKA 功能。

管理端已有 module list、enable、disable、config update 與 compatibility API。前端的能力目錄也把「已部署、租戶啟用、執行健康、我的權限」分成四個狀態顯示，避免把「已安裝」誤當成「使用者可以操作」。

### 2. 租戶自己的職能與組織語言

目前可依租戶維護：

- Job Role 與使用者兼任職能。
- 職能預設可見的模組與部門範圍。
- 公司專有詞典：料號、客戶、設備代碼、別名、發音提示、常見誤聽與模組範圍。
- 部門、使用者、RBAC 與資料權限。

這讓同一個 MKA 功能，在 A 公司可以叫「異常單」、在 B 公司可以叫「品質事件」；語音辨識也可以理解該公司的料號和設備代稱。

### 3. 租戶自己的表單、規則、簽核與情境

目前可做的設定式調整包括：

- 租戶 scoped 的表單定義、UI Schema、版本與有效日期；目前主要由內建 fixed-form Schema／後端 provisioning 建立，尚無完整的租戶自助式表單設計器。
- DOCX／XLSX 公司版型與欄位 mapping。
- 租戶版規則集的資料模型與測試案例欄位；目前仍需工程／後端交付，尚無完整自助式規則設計 UI。
- 多級簽核步驟，以及可保存的代理與逾時 policy；代理／逾時的全面自動執行仍未完成驗證。
- QR 場景對應的廠區、產線、設備、產品、工單與文件版本。
- 模組的允許角色、部門、職能、知識範圍、工具與 UX 入口。

### 4. 租戶體驗組裝

登入後的 `/experience/bootstrap` 會由伺服器回傳實際可用的：

- deployment capabilities。
- tenant module bindings。
- 使用者權限與職能。
- UI module manifests、導航、workspace cards 與預設首頁。

因此前端不是把所有製造功能硬塞給每個人，而是依當前租戶與使用者實際可用能力組裝畫面。後端仍是權限與可操作性的最終權威。

### 第六層目前的界線

目前 Tenant Solution 的強項是「可治理的設定與模組組合」，不是任意客製程式的承諾。

現階段尚不應宣稱已具備：

- 無需工程師的全功能低碼流程設計器。
- 任意第三方 ERP／MES 的即插即用雙向寫入。
- 每個租戶可自行撰寫並安全部署自訂程式。
- 共享多租戶 Commercial GA。

第一個真實租戶仍應採專屬 deployment 或專屬資料庫；production 雖已啟用 RLS，但 FORCE RLS rollout 與 application role 切換尚未完成，不能把互不相關的真實企業放入同一共享資料庫後宣稱 GA。

---

## 三層如何一起工作：以「設備異常」為例

```text
第六層：某租戶設定
  - QR token 對應 A 廠、二號線、EQ-100
  - 班長需核准，超過兩小時通知品保
  - 使用該公司自己的異常表單與設備代碼

第五星：MKA 的 incident_handover 模組
  - 提供現場作業入口、異常／交接班的專業操作畫面

第四層：Workflow primitives
  - 建立任務、帶入掃碼情境、填表、保存欄位來源
  - 送簽、記錄決策、通知、匯出、保留 audit

前三層：共同地基
  - 只檢索該租戶、該設備、該角色有權看的 SOP 與維修知識
  - 讓回答、填表與決策都能回到 Evidence
```

---

## 後續演進原則

1. **先設定，後開發。** 優先用 binding、權限、詞典、表單、規則、簽核、scene 與模板滿足租戶需求。
2. **先抽成 Pack，再做專屬 extension。** 第二個租戶也可能需要的能力，應新增或改善 Pack，不應埋進單一租戶分支。
3. **可重用的流程能力回歸第四層。** 當第二個 Pack 也需要任務、簽核、表單或場景時，應把契約與服務從 MKA 邊界抽為真正 Workflow Kernel。
4. **核心不認識特定客戶流程。** 平台仍只負責租戶、權限、知識、Input、Evidence 與共通 workflow contract。
5. **高風險寫入維持人工決策。** 對 ERP、MES、設備或正式文件的寫入，必須經權限、簽核、可追溯紀錄與必要 rollback。

這樣第四層會越來越通用、第五層會越來越多可選模組、第六層可以愈來愈貼近不同製造企業，但前三層仍保持穩定且容易維護。

---

## 2026-08-29 第二輪程式對照結果

本文件已再次對照 Pack composition root、MKA manifest、前端 route bundle、任務種子、Task Engine、Module Registry、tenant lifecycle、表單模板與 Experience Bootstrap。

- 確認 `app/packs/` 目前只有 MKA 一個實際 Pack。
- 確認 MKA manifest 為 `1.0.0`、`beta`，並宣告五個 module key。
- 確認前端只有 MKA bundle，實際擁有 `/job`、task、forms、approvals、knowhow 等 route keys。
- 確認八個全域 TaskDefinition 種子與租戶／職能／能力三層 runtime gate。
- 確認一般租戶沒有啟用 binding 時看不到 MKA；預設全開只發生在明確指定的受控 provisioning／seeder。
- 確認 RuleSet 尚無完整通用管理 API／UI；逾時與代理 policy 可保存但不可宣稱全面自動化。
- 相關回歸：`test_pack_runtime`、`test_p4_module_platform`、`test_p2_task_engine`、`test_experience_bootstrap` 共 62 項通過。
