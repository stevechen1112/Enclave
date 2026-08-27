# Enclave 模組化多租戶、多模態企業知識平台架構調整

**文件狀態**：Architecture Target + Incremental Migration Plan
**建立日期**：2026-08-26
**適用範圍**：Enclave Core、Knowledge Engine、MKA、Web/PWA、Connector、Sidecar、未來音訊與影片能力
**決策原則**：不推倒重寫；先建立穩定契約與單向依賴，再逐模組遷移

---

## 1. 決策摘要

Enclave 的產品核心調整為：

> 以多租戶控制平面為安全與商業基礎，以版本化企業知識核心為產品中心，以多模態知識擷取為主要輸入能力，並以通用工作流核心承載可選的產業、職能與租戶專屬模組。

目標分層：

1. **Multi-tenant Control Plane**：租戶、身分、權限、資料政策、配額、模組授權、稽核。
2. **Enterprise Knowledge Kernel**：知識單元、版本、發布、檢索、引用、拒答、回饋與保鮮。
3. **Multimodal Ingestion Fabric**：文件、表格、圖片、音訊、影片、Connector 與 API 資料的統一擷取管線。
4. **Workflow Kernel**：Task、Form、Rule、Approval、Export、Write Guardrail 等跨模組共用原語。
5. **Domain Packs**：製造業業務、現場、品保、維修、採購、訓練等可選模組。
6. **Tenant Solutions**：租戶版型、欄位、流程、規則、整合與必要的專屬擴充。

第一至第四層是平台；第五、六層是可選、可替換、可持續增加的產品能力。

---

## 2. 為什麼需要調整

現有系統已具備多租戶、文件入庫、pgvector、混合檢索、Knowledge Gateway、KB revision、Task Engine、表單、簽核、知識卡與 Outbox 等重要能力，不適合重寫。

但目前仍存在幾個長期擴張風險：

1. **核心與 MKA 直接耦合**：例如 `RetrievalFacade` 直接查詢 MKA know-how repository。
2. **輸入管線以 Document 為中心**：短音訊、長訪談與文件分屬不同流程；影片加入後容易再形成第四條管線。
3. **模組啟用有部署級與租戶級混雜**：環境變數、product pack、tenant module binding 的責任需要明確分離。
4. **前端路由為靜態編譯**：MKA 頁面直接掛在主 `App.tsx`，租戶模組只能隱藏，尚不是完整的模組組裝。
5. **部分能力有平行實作或歷史相容路徑**：若持續增加場景，會提高測試、治理與認知成本。
6. **引用定位偏文件型**：page/bbox 已有，但音訊與影片需要 speaker、time range、frame 等統一定位語意。

本次調整不是把 monolith 改成大量 microservices，而是先建立一個有明確邊界的 **modular monolith**。

---

## 3. 架構不變量

### 3.1 依賴方向

```text
tenant_extensions ─┐
domain_packs ───────┼──> workflow/platform contracts
                    └──> knowledge/platform contracts

platform/core  ─X─> domain_packs
domain_pack A  ─X─> domain_pack B（除非透過公開契約或事件）
```

- Platform 不得 import MKA 或任何產業 pack。
- Pack 透過 provider、handler、projector、route、navigation 等 registry 接入。
- 跨 pack 協作使用版本化契約或 domain event，不直接讀取彼此內部 repository。
- 核心資料權威留在 Enclave canonical store；sidecar 只保存衍生 projection。

### 3.2 多租戶

所有 tenant-owned 資料、快取、物件、事件、背景任務與 sidecar binding 都必須帶有 tenant identity。

有效權限至少是以下條件的交集：

```text
tenant match
AND KB membership / immutable revision scope
AND department policy
AND source ACL
AND resource not tombstoned / denied
AND module entitlement
AND domain applicability
```

### 3.3 知識發布

- 解析完成不等於可以回答。
- 低信心 artifact 必須 provisional 或進人工 review。
- 一般問答只能讀取 active revision 與 answer-ready knowledge。
- 高風險程序不得由 narrative fallback 自行補足條件或選擇分支。
- 每個使用者可見 claim 必須有穩定 evidence reference。

### 3.4 模組可選性

模組是否可用由三層共同決定：

```text
deployment capability available
AND tenant entitlement/binding enabled
AND user authorization allows
```

模組「移除」原則上是停用 tenant binding 與移除導覽、任務、provider、projection；不為每個租戶建立不同程式碼分支。

---

## 4. 目標邏輯架構

```text
┌──────────────────────────────────────────────────────────────┐
│ Clients                                                       │
│ Web / PWA / Mobile / API / Capture UI                         │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│ Tenant Experience Composer                                   │
│ capability bootstrap / navigation / module routes / UX state │
└───────────────┬───────────────────────────────┬──────────────┘
                │                               │
┌───────────────▼──────────────┐  ┌─────────────▼──────────────┐
│ Workflow Kernel             │  │ Enterprise Knowledge Kernel │
│ Task / Form / Rule          │  │ QueryPlan / Retrieval        │
│ Approval / Export / Write   │  │ Evidence / Citation / Refusal│
└───────────────┬──────────────┘  │ Release / Feedback / Freshness│
                │                 └─────────────▲───────────────┘
                │                               │
┌───────────────▼───────────────────────────────┴──────────────┐
│ Domain Pack Runtime                                           │
│ provider / handler / projector / policy / UI manifest         │
└───────────────────────────▲──────────────────────────────────┘
                            │
┌───────────────────────────┴──────────────────────────────────┐
│ Multimodal Ingestion Fabric                                  │
│ upload/capture/connect → asset → artifact → knowledge unit    │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│ Multi-tenant Control Plane + Canonical Data Plane             │
│ identity / ACL / RLS / storage / outbox / audit / quota       │
│ PostgreSQL + pgvector / Redis / Local or S3 storage            │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. 多模態資產模型

現有 `Document` 在遷移期間繼續運作，但新的通用契約以 Asset 為中心。

### 5.1 SourceAsset

代表使用者或 connector 放入系統的原始來源：

- document
- spreadsheet
- image
- audio
- video
- email
- web page
- dataset
- external record

必要欄位：

```text
tenant_id
asset_id
asset_kind
media_type
source_system / source_record_id
content_uri
content_hash
data_classification
acl_reference
created_by / captured_by
```

### 5.2 AssetRevision

每次內容更新形成不可變 revision，不在原 revision 上覆寫：

```text
asset_id + revision
content_hash
external_version
effective period
ingestion status
retention policy
supersedes / superseded_by
```

### 5.3 DerivedArtifact

解析器、OCR、ASR、VLM 或人工處理產生的衍生物：

- extracted_text
- layout_page
- ocr_region
- table
- transcript_segment
- keyframe
- video_scene
- audio_event
- procedure_candidate
- entity_candidate

Artifact 必須記錄 provider、provider version、confidence、content hash、quality state 與 evidence locator。

### 5.4 KnowledgeUnit

不同輸入最後投影為共同知識語意：

- narrative
- row
- field
- procedure
- knowhow
- entity
- compiled

Domain pack 可以產生新的 KnowledgeUnit，但不能繞過 tenant、ACL、revision、review 與 citation。

### 5.5 EvidenceSpan

Evidence locator 使用 tagged/typed location，而不是把所有格式塞進 page/bbox：

| 輸入 | 定位欄位 |
|---|---|
| 文件 | page、section、bbox |
| 表格 | worksheet、table、row、column、cell range |
| 圖片 | bbox、region label |
| 音訊 | start_ms、end_ms、speaker |
| 影片 | start_ms、end_ms、frame_index、bbox、track_id |
| Connector/API | source_system、source_record_id、field path |

同一個 claim 可有多個 EvidenceSpan，例如影片步驟同時引用逐字稿時間段與關鍵幀。

---

## 6. 統一 Ingestion Fabric

```text
Source Adapter
→ tenant/ACL/data-classification envelope
→ immutable asset revision
→ malware/media validation
→ capability routing
→ parser/transcriber/analyzer adapters
→ derived artifacts
→ quality/readiness assessment
→ human review when required
→ knowledge projection
→ candidate publication
→ index artifacts
→ active knowledge release
```

### 6.1 Capability Router

路由依據不是副檔名 alone，而是：

- media type
- content sniffing
- page/duration/resolution
- digital vs scanned
- language
- table/layout density
- tenant data-residency policy
- provider availability
- cost/latency budget
- requested knowledge capability

### 6.2 Provider 契約

每個 provider 必須公開：

- supported asset/artifact kinds
- input constraints
- local/cloud boundary
- output schema version
- confidence semantics
- timeout/retry/idempotency behavior
- cost measurement
- license and data retention notes

### 6.3 音訊與影片

音訊與影片不得只產生一篇 transcript。至少應支援：

```text
audio/video demux
→ VAD / diarization / timestamped ASR
→ scene or shot segmentation
→ keyframe extraction + OCR
→ optional action/audio-event candidates
→ temporal alignment
→ human review
→ procedure/knowhow projection
```

第一版影片 MVP 不承諾全自動理解所有操作；先完成 timestamped transcript、keyframes、OCR、人工結構化與時間軸引用。

---

## 7. Enterprise Knowledge Kernel

核心只認識通用契約，不認識「報價」「8D」「師傅」等產品名詞。

### 7.1 Knowledge Provider

Domain pack 若需要把自己的 approved knowledge 加入檢索，實作 `KnowledgeProvider`：

```text
contribute(KnowledgeContributionContext)
  → Iterable[KnowledgeCandidate]
```

`KnowledgeContributionContext` 必須包含 query、AuthorizationContext、Session、scope、
top_k、domain 與 mode。Provider 必須自行執行 domain applicability；Registry 負責
tenant identity 驗證、schema/version 驗證、per-provider 上限、隔離失敗與統一 audit
metadata。Registry 回傳 `KnowledgeContributionBatch`，其中 failure 不得被偽裝成查無資料。

### 7.2 Knowledge Projector

把 Asset/Artifact 投影為 KnowledgeUnit：

```text
project(asset_revision, artifacts, tenant_policy)
  → provisional knowledge units
```

### 7.3 Evidence與回答

正式回答管線維持：

```text
AuthorizationContext
→ QueryPlan
→ multi-arm retrieval
→ provider contributions
→ canonical visibility revalidation
→ fusion
→ EvidenceContract
→ refusal or generation
→ source verification
→ user-visible citation
```

---

## 8. Workflow Kernel 與 Domain Pack

### 8.1 Workflow Kernel 保留的原語

- TaskDefinition / TaskRun / TaskRunEvent
- input schema / field source / provenance
- deterministic rule execution
- FormDefinition / FormInstance
- approval policy / immutable snapshot / decision log
- export renderer
- write request / approval token / idempotency / rollback audit
- notification and review reminder interface

### 8.2 Domain Pack Manifest

每個 pack 應有版本化 manifest：

```json
{
  "pack_key": "manufacturing.quality",
  "version": "1.0.0",
  "required_platform_version": ">=3.0",
  "capabilities": ["field_work", "approval"],
  "knowledge_providers": [],
  "knowledge_projectors": [],
  "task_handlers": [],
  "routes": [],
  "navigation": [],
  "permissions": [],
  "feature_flags": []
}
```

Pack 的 DB migration 必須可追蹤，但不得任意修改其他 pack 的資料表。

### 8.3 租戶專屬差異

優先順序：

1. tenant config
2. schema/field/rule DSL
3. template
4. integration adapter
5. tenant extension package

除非上述都無法表達，否則不建立 tenant-specific core branch。

---

## 9. 建議程式目錄

遷移後目標：

```text
app/
├─ platform/
│  ├─ tenancy/
│  ├─ assets/
│  ├─ knowledge/
│  ├─ workflow/
│  ├─ governance/
│  └─ integrations/
├─ packs/
│  ├─ mka/
│  ├─ manufacturing_sales/
│  ├─ manufacturing_operations/
│  ├─ quality/
│  ├─ maintenance/
│  └─ training_knowhow/
├─ composition/
│  ├─ providers.py
│  ├─ task_handlers.py
│  └─ web_modules.py
├─ api/
└─ tasks/
```

遷移期間允許舊 `app/services` 與新 `app/platform` 並存，但新核心不得再增加對 `app.models.mka` 或 pack service 的直接 import。

---

## 10. 前端模組化

目標從靜態 route 改為 tenant-aware module composition：

```text
experience/bootstrap
→ deployment capabilities
→ tenant module bindings
→ user capabilities/job role
→ module manifests
→ navigation + routes + workspace cards
```

前端 pack manifest 至少包含：

- route key / lazy component
- navigation label/icon/order
- required capability
- module key
- empty/loading/error states
- mobile availability
- telemetry namespace

安全端點仍必須在後端驗權；前端隱藏只是 UX，不是安全邊界。

---

## 11. Sidecar 與外部服務邊界

- RAGFlow：解析/OCR provider，不是 canonical document store。
- PipesHub：connector provider，不是最終 ACL authority。
- WeKnora：compiled/wiki/graph projection，不是 active KB revision authority。
- Ollama/OpenAI/Gemini/Voyage：模型 provider，輸入需受 tenant data policy 路由。
- ERP/MES/CRM：外部 effect target，任何 mutation 必須通過 write guardrail。

Sidecar 關閉或失敗時，平台必須明確降級，不得回報假完成或假收斂。

---

## 12. 遷移計畫

### Phase A：邊界建立（本輪開始）

- 建立本文件與 dependency rules。
- 建立平台級 KnowledgeProvider registry。
- 將 know-how contribution 從 RetrievalFacade 搬到 MKA provider。
- 建立 Asset/Artifact/EvidenceSpan Python contract。
- 新增 architecture tests，禁止核心重新直接 import MKA provider internals。

### Phase A.1：契約收口（已完成第一切片）

- Provider entry 強制唯一 key、version、capability metadata。
- Provider candidate 使用 typed `KnowledgeCandidate`，並驗證 tenant identity。
- scope、top_k、domain、mode 進入 provider context；明確 KB revision 不得被 pack 擴大。
- provider failure 結構化回傳並使 retrieval 標示 partial/degraded。
- provider candidate 必須依序通過 visibility、FusionPolicy、global top_k 與 CitationBuilder。
- citation 支援 document 以外的 canonical resource identity；舊 document 欄位保留相容。
- SourceAsset 與 AssetRevision contract 分離；EvidenceSpan 強制 asset revision 與 coordinate space。

### Phase B：統一資產身分

**狀態：開發與 code review gate 已通過（2026-08-26）。**

- 已新增 SourceAsset、AssetRevision、DerivedArtifact、EvidenceSpan DB migration。
- 已建立 Document → SourceAsset 相容 projection 與租戶分批 backfill command。
- 文件上傳、connector、watcher/legacy worker、URL ingestion 已 dual-write；read path 尚未切換。
- 音訊 capture 已以不可變 manifest AssetRevision 保存來源，逐字稿產生 temporal EvidenceSpan。
- PostgreSQL 全鏈 upgrade、Phase B downgrade/re-upgrade 與 schema drift check 已通過。
- Code review 記錄：`docs/PHASE_B_ASSET_IDENTITY_CODE_REVIEW.md`。

### Phase C：統一 Ingestion Job

**狀態：開發與 code review gate 已通過（2026-08-26）。**

- 已建立 IngestionJob 狀態機、事件歷程與版本化 adapter registry。
- document、URL 與 long interview task 已接入共同 orchestrator。
- artifact quality/readiness、retry attempt 與 failure 使用共同 lifecycle。
- 舊 endpoint/Celery task 名稱保留為相容層，沒有新增第三套 pipeline。
- PostgreSQL migration roundtrip 與 schema drift check 已通過。
- Code review 記錄：`docs/PHASE_C_INGESTION_ORCHESTRATION_CODE_REVIEW.md`。

### Phase D：Pack Runtime

- 建立 pack manifest 與 backend registry。
- 把 MKA 分拆為第一批 packs。
- 將 Task handlers、Knowledge Providers、Projectors、permissions 由 composition root 組裝。
- product env flags 只描述部署能力；租戶 binding 決定實際啟用。

**狀態（2026-08-26）：已完成並通過 gate。**

- 已建立版本化、不可變的 Pack Runtime，包含 dependency、capability 與唯一 key 驗證。
- MKA 已透過 manifest 貢獻 knowledge provider、task handlers、projectors 與 permissions。
- `PACK_MKA_ENABLED` 僅控制部署能力；既有 `TenantModuleBinding` 仍是租戶實際啟用權威。
- 關閉 MKA pack 後，其 backend contributions 全部移除，核心檢索仍可獨立運作。
- Code review 記錄：`docs/PHASE_D_PACK_RUNTIME_CODE_REVIEW.md`。

### Phase E：前端模組化

- 將 `App.tsx` MKA route 移到 module route registry。
- bootstrap 回傳 tenant-enabled UI manifests。
- navigation/workspace 共用同一 eligibility decision。
- 六 persona E2E 覆蓋每個 module enable/disable 組合。

**狀態（2026-08-26）：已完成並通過 gate。**

- `App.tsx` 不再硬編碼 MKA pages；route ownership 已移至 UI module registry。
- bootstrap 回傳 tenant-enabled UI manifests，route、navigation、default home 與 workspace 共用同一 eligibility decision。
- pack 或租戶停用時，routes、navigation、workspace 與互動能力一起 fail-closed。
- 六個 Demo personas 與六種 manifest 組合均有自動化覆蓋。
- Code review 記錄：`docs/PHASE_E_FRONTEND_MODULARITY_CODE_REVIEW.md`。

### Phase F：影片知識管線

Phase F 以三個可獨立驗收、各自 code review 的子階段完成，不將基礎版誤報為完整多模態理解。

#### F1：基礎影音管線與證據覆核

- video SourceAsset、metadata probe、duration/codec limits。
- 原檔 SHA-256、租戶邊界、資料分類、ACL 參照與受控媒體存取。
- demux、timestamped transcript、keyframe/OCR artifact。
- Review UI：逐字稿、關鍵幀、步驟與時間軸對齊。
- temporal EvidenceSpan 與播放器 deep link。
- know-how/procedure candidate → review → active publication。

#### F2：多模態時間軸理解

- VAD/說話者分離 provider、鏡頭邊界與事件關鍵幀。
- 動作事件、設備/參數狀態、異常聲音、置信度與來源 provider 標記。
- 語音、OCR、畫面、聲音事件依時間範圍對齊，並保留一對多 EvidenceSpan。
- 未安裝/未啟用專業 provider 時必須 fail-closed 標示 unavailable，不得以啟發式結果假裝模型辨識。

#### F3：結構化程序、SOP 衝突與發布治理

- 將有證據的句子分類為步驟、前置條件、判斷規則、風險、例外與禁止動作。
- 對租戶的正式 SOP 版本執行衝突檢查，SOP 權威層級優先。
- 未解決衝突、低信心或高風險內容不得發布。
- 覆核決策、衝突處置、適用機台、版本與生效日均須可追溯。

**狀態（2026-08-26）：F1、F2、F3 皆已完成並分別通過 code review gate。**

- 影片從原檔、hash/ACL、demux、ASR/OCR/scene、聲學離群、時間窗對齊，到結構化程序與核准發布已具備單一可追溯管線。
- 動作/設備候選預設為有明確原文或 OCR 證據的保守規則；聲學離群不宣稱故障診斷。專業視覺動作、語意聲音故障與 diarization 模型透過 provider 插入，未啟用時 UI/API 明確標示候選方法或 unavailable。
- 正式 SOP 衝突保留文件版本與 chunk 證據；未處置衝突、未確認高風險或未經主管級角色核准均無法發布。
- Code review 記錄：`docs/PHASE_F1_VIDEO_FOUNDATION_CODE_REVIEW.md`、`docs/PHASE_F2_MULTIMODAL_TIMELINE_CODE_REVIEW.md`、`docs/PHASE_F3_VIDEO_GOVERNANCE_CODE_REVIEW.md`。

### Phase G：舊路徑退場

- 用 telemetry 確認無流量後移除 legacy manager、duplicate endpoint 或 parallel service。
- schema/table 只在備份與 rollback 演練通過後退場。
- 更新 capability claims、runbook、SDK 與客戶升級指南。

**狀態（2026-08-27）：退場機制已完成並通過 code review gate；客戶相容路徑正式進入 observe window。**

- 所有 FastAPI method/path 註冊均無衝突；原本不可達的重複 `/job-modules` GET 已合併為單一 canonical contract。
- 16 個 frontend legacy redirects 已具備 tenant-scoped usage telemetry、admin report 與唯一 registry。
- observe 階段不可刪除；各租戶完整 30 天零流量、公告、disable 與回滾演練是後續 removal PR 的必要證據。
- Runbook：`docs/runbooks/LEGACY_SURFACE_RETIREMENT.md`；升級指南：`docs/release/MODULAR_PLATFORM_UPGRADE_GUIDE.md`；code review：`docs/PHASE_G_LEGACY_RETIREMENT_CODE_REVIEW.md`。

---

## 13. 每階段驗收閘門

### 架構

- Platform source 不 import pack internals。
- 所有 registry entry 有唯一 key、version 與 capability metadata。
- 關閉任一 pack 後 core test 與基本問答仍通過。

### 多租戶與安全

- tenant、department、source ACL、KB revision、deny/tombstone pairwise tests。
- background task 與 object key tenant assertion。
- pack disable 後 API、retrieval、UI 三處都不可繼續使用。

### 多模態

- 原始 asset、artifact、knowledge unit 可逐層追溯。
- 每個 user-visible evidence 可回到精確頁面/列/時間段/畫面。
- 低信心內容不自動進 active corpus。

### 相容性

- 既有文件問答與 MKA E2E 不退步。
- 舊 API 在公告的 compatibility window 內維持。
- migration 可從正式 schema 升級且有 rollback/restore 證據。

### 品質

- 新架構不得以既有開發題重跑冒充泛化改善。
- 影片/音訊需另建 holdout 與人工時間軸 ground truth。
- 每個 pack 有自己的 domain acceptance，平台另有跨領域 sealed evaluation。

---

## 14. 主要風險與控制

| 風險 | 控制 |
|---|---|
| 大爆炸重寫造成回歸 | strangler migration、dual-write、compatibility adapter |
| 抽象過度，開發速度下降 | 只抽已有兩個以上實作或已確定的 audio/video contract |
| plugin 數量失控 | manifest、版本相容矩陣、registry uniqueness、pack ownership |
| tenant 客製變成 fork | config/DSL/template/adapter 優先，extension package 次之 |
| 多模態成本失控 | tenant budget、provider routing、artifact reuse、按需高成本分析 |
| AI 自動萃取錯誤 | provisional state、confidence、人工 review、active publication gate |
| sidecar 成為隱性權威 | canonical revalidation、outbox convergence、可重建 projection |

---

## 15. 本輪實際交付與後續邊界

本輪已依 Phase B–G 順序完成施工，且每個完整 phase 都在進入下一階段前通過獨立 code review gate：

1. canonical Asset／Revision／Artifact／EvidenceSpan 資料契約與相容 projection。
2. 統一 Ingestion Job、事件歷程、adapter registry 與 worker lifecycle。
3. Pack Runtime、MKA composition root、部署能力與租戶 binding 分離。
4. 前端 module registry、tenant-enabled manifest、route/navigation/workspace fail-closed。
5. 影片 F1–F3：受治理匯入、影音解析、多模態時間軸、結構化程序、SOP 衝突與人工發布。
6. Legacy route telemetry、退場 gate、唯一 API contract、升級與回滾 runbook。

本輪刻意沒有將下列事項宣稱為已完成：

- 專用視覺動作辨識、設備狀態模型、語意異音故障診斷與高品質 diarization 模型；目前採 provider contract，缺少專業模型時明確標示 unavailable 或 evidence-rule candidate。
- 舊 route/table/object 的實體刪除；必須先累積逐租戶 observe telemetry，通過公告、30 天零流量、disable 與回滾演練。
- 影片知識抽取的跨產業泛化品質；仍須建立獨立 holdout、人工 ground truth 與 domain acceptance 才能提出準確率宣稱。

完整整合驗收記錄見 `docs/FINAL_MODULAR_PLATFORM_CODE_REVIEW.md`。

第一階段完成後的權威收斂、Pack 全表面模組化與 UI/UX 漸進重構，依
`docs/ARCHITECTURE_AUTHORITY_AND_UIUX_REFACTOR_PLAN.md` 的 Phase H–M 執行。
