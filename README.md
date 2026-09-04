# Enclave — 模組化多租戶、多模態企業知識平台

> 以多租戶控制平面為安全與商業基礎，以版本化企業知識核心為產品中心，
> 以多模態知識擷取為主要輸入能力，再以可選 Domain Packs 承載製造業職能、
> 工作流與租戶專屬應用。

Enclave 的核心不是單一聊天機器人，也不是把多套 AI 工具 UI 拼在一起。系統把
文件、表格、圖片、音訊、影片、網址、Connector 與外部紀錄收斂成同一套可追蹤的
Asset、Artifact、Knowledge Unit、Evidence、Review 與 Release 生命週期；回答與應用
輸出都必須服從租戶、權限、版本、證據與發布治理。

## 目前狀態（2026-09-04）

| 項目 | 狀態 |
|---|---|
| 工作區程式基線 | Phase B–M、影片 F1–F3、UI/UX UX-A–UX-D 已完成並通過各階段 Code Review |
| 核心架構 | 多租戶平台、Enterprise Knowledge Kernel、多模態 Ingestion Fabric、Workflow Kernel、Domain Pack Runtime 已建立 |
| 最新瀏覽器驗收 | 已以李永仁 owner 帳號在 current release 檢查總覽、所有資產、人工確認、音檔詳情與 Ask；5 個來源皆完成系統處理、0 失敗、console error／warning 0。未代替客戶核准內容，因此 Ask 維持 0 筆可問答是正確治理結果 |
| 前端最新回歸 | ESLint、TypeScript、Vitest 41 個測試檔／140 項測試、Vite production build 與乾淨 Docker release build 全部通過；iPhone Safari／Android Chrome 的獨立實機認證仍屬 Commercial GA gate |
| 後端最新回歸 | 既有 Input I8 全量基線為 1,500 passed／12 skipped／0 failed；I10 另完成變更範圍測試、fresh PostgreSQL＋pgvector migration from zero 及 8/8 DB 整合回歸 |
| Input 平台化 | Input I0–I10 工程與逐階段 Code Review 已完成；I10 補上 capability／confidence 契約、跨模態狀態、正式 truth-corpus 驗收工具、來源層級低風險確認與 evidence locator。流程與服務可用；跨格式語意品質仍須以客戶第二輪、獨立人工標註的 truth corpus 驗收，不宣稱 SLA／GA |
| 後端架構基線 | P4 全量回歸 1,314 passed／12 skipped／0 failed；100 張保護表、3 租戶 × 100 shadow comparisons 與 FORCE-RLS 攻擊矩陣 11 passed |
| 正式站 | [https://kachu.tw](https://kachu.tw) 已部署 `rta-i10-a67e937`（source `a67e93743f834f016dafa9b50f95590b00d2ea27`、schema `input_i10_confidence_001`）；backend／frontend release parity、service health、TLS、登入、Provider 7/7 與第一租戶 current-release 瀏覽器驗收 PASS |
| 必要 AI／Input Provider | 主問答 OpenAI、內部分類 Gemini、掃描理解 Gemini、bge-m3 embedding、短語音 TTS→STT、長音檔說話者辨識、Cloud OCR 已於 production 逐項真實呼叫 7／7 PASS；未讀取額外 `api key.txt` |
| 產品化 Phase | P0–P4 PASS；P5 工程與內部 review 完成，商用規模 live evidence 為 WAIVED／NOT RUN；P6 internal software gate 與 Code Review PASS；實體裝置 campaign 保留為 Commercial GA gate |
| 首租戶導入 | 八策股份有限公司／管理部已建立 2 位具名使用者，陳宥竹與李永仁目前皆為 owner；李永仁既有 5 個來源均已完成機器處理並等待人工確認，歷史 capability 狀態已回填。租戶只啟用 Input＋Knowledge／Ask 核心，場景模組 binding 為 0；第二輪真人高量與語意真值驗收仍獨立進行 |
| Production 租戶隔離 | application login 已切為 `enclave_app`（`NOSUPERUSER`、`NOBYPASSRLS`），111/111 張保護表已啟用 FORCE RLS，policy drift 為 0；隔離 canary、production 攻擊矩陣 11/11、shadow parity、Worker／Beat 與回滾演練均 PASS |
| Legacy removal | HOLD；相容路徑仍在 observe window，不得提前刪除 |
| 商業 GA | 未宣稱；工程完成狀態與外部商業、法律、滲透、真機及真人活動分開管理，後者不作為開發完成條件 |

完整驗收證據：

- `docs/FINAL_MODULAR_PLATFORM_CODE_REVIEW.md`
- `docs/FINAL_AUTHORITY_AND_UIUX_CODE_REVIEW.md`
- `docs/FINAL_UIUX_EXPERIENCE_CONVERGENCE_CODE_REVIEW.md`
- `docs/PHASE_P0_RELEASE_PARITY_CODE_REVIEW.md`
- `docs/PRODUCTION_INPUT_I8_DEPLOYMENT_ACCEPTANCE_2026-08-29.md`
- `docs/PRODUCTION_ASK_DECISION_DEPLOYMENT_ACCEPTANCE_2026-08-29.md`
- `docs/PHASE_PROVIDER_RUNTIME_GATE_CODE_REVIEW_2026-09-01.md`
- `docs/PRODUCTION_PROVIDER_RUNTIME_GATE_ACCEPTANCE_2026-09-01.md`
- `docs/LAYER_4_5_6_CURRENT_STATE_2026-08-29.md`
- `docs/SCENARIO_APPLICATION_ZERO_BASELINE_2026-08-29.md`
- `docs/APPLICATION_LAYER_ZERO_BASE_PORTFOLIO_REVIEW_2026-08-29.md`
- `docs/APPLICATION_DECOUPLING_IMPLEMENTATION_PLAN_2026-08-29.md`
- `docs/PHASE_APPLICATION_A0_BOUNDARY_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_APPLICATION_A1_CORE_CAPABILITIES_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_APPLICATION_A2_WORKFLOW_KERNEL_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_APPLICATION_A3_INDEPENDENT_CONTRACT_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_APPLICATION_A4_LIFECYCLE_ACCEPTANCE_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_APPLICATION_A5_PHYSICAL_WORKFLOW_DECOUPLING_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_APPLICATION_A6_BACKEND_PACK_SPLIT_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_APPLICATION_A7_FRONTEND_BUNDLE_SPLIT_CODE_REVIEW_2026-08-29.md`
- `docs/CORE_EXPERIENCE_01_EVIDENCE_QA_DEFINITION_2026-08-29.md`
- `docs/APPLICATION_HYPOTHESIS_FIELD_INCIDENT_2026-08-29.md`
- `docs/PHASE_P1_CI_SUPPLY_CHAIN_SECURITY_CODE_REVIEW.md`
- `docs/PHASE_P2_TENANT_HARD_ISOLATION_CODE_REVIEW.md`
- `docs/reports/PHASE_P2_STAGING_FORCE_RLS_VERIFICATION_2026-08-28.md`
- `docs/PHASE_P3_MULTIMODAL_GOLDEN_CORPUS_CODE_REVIEW.md`
- `docs/PHASE_P4_RESILIENCE_DR_CODE_REVIEW.md`
- `docs/reports/P4_RESILIENCE_EVIDENCE_2026-08-28.json`
- `docs/reports/P6_UIUX_DEVICE_CODE_REVIEW_2026-08-28.md`
- `docs/decisions/P5_LIVE_VALIDATION_WAIVER_2026-08-28.md`
- `docs/UIUX_BROWSER_ACCEPTANCE_2026-08-27.md`
- `docs/PHASE_INPUT_I0_CONTRACT_EVIDENCE_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_INPUT_I1_INTAKE_UX_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_INPUT_I2_RESUMABLE_UPLOAD_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_INPUT_I3_CORE_CAPTURE_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_INPUT_I4_DOCUMENT_IMAGE_QUALITY_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_INPUT_I5_AUDIO_VIDEO_PRODUCTIZATION_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_INPUT_I6_CONNECTOR_BULK_IMPORT_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_INPUT_I7_CAPACITY_RESILIENCE_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_INPUT_I8_FIRST_TENANT_PILOT_CODE_REVIEW_2026-08-29.md`
- `docs/PHASE_INPUT_I8_PREPILOT_HARDENING_CODE_REVIEW_2026-08-29.md`
- `docs/reports/INPUT_I3_DEVICE_VALIDATION_MATRIX_2026-08-29.md`

### 第一個租戶導入定位

目前版本已可承接第一個付費設計夥伴／受控試營運租戶，但這不等於共享式、自助式
SaaS 已達 Commercial GA。Production least-privilege role 與 FORCE RLS 技術切換已完成；
擴大共享式多租戶流量前仍須完成既定觀察期、外部滲透與營運容量證據。

建議首案範圍：

- 一個企業／廠區、5–30 位具名使用者、一位企業知識負責人。
- 先選一個可量測價值、失誤後果可控的場景，例如教育訓練、SOP 查詢或知識傳承。
- 初期不讓 AI 自動控制機台，也不直接寫入 ERP／MES；高風險回答仍須正式 SOP 與人工核准。
- 先以客戶自有的 20–50 份代表性資料建立驗收集，量測引用正確率、拒答、權限與任務完成率。
- 上線前完成真實 iPhone／Android 的相機、麥克風、長音檔／影片、弱網與工廠噪音驗收。
- 明確約定資料保留、匯出、刪除、備份還原、外部 AI provider、事件回報與支援窗口。
- P5 live capacity／degradation／soak 尚未執行期間，採保守配額、檔案大小限制、併發限制與人工監控。

現階段不得宣稱共享多租戶 GA、24／7 SLA、已證實的商用容量，或讓 AI 獨立執行
高風險現場操作。這些是後續正式擴張的 gate，不妨礙以專屬環境開始第一個受控客戶案。

---

## 1. 產品分層

Enclave 以六層責任邊界發展；第一至第四層是平台，第五、六層可依租戶需求增減。

1. **Multi-tenant Control Plane** — 租戶、身分、RBAC、部門政策、RLS、資料分類、配額、模組授權、稽核與保留政策。
2. **Enterprise Knowledge Kernel** — Knowledge Unit、版本、發布、檢索、引用、拒答、證據驗證、回饋與保鮮。
3. **Multimodal Ingestion Fabric** — 文件、試算表、圖片、音訊、影片、網址、Connector、API 與外部紀錄的統一擷取管線。
4. **Workflow Kernel** — Task、Form、Rule、Approval、Export、Notification、Write Guardrail 與 rollback audit。
5. **Domain Packs** — 製造業業務、現場、品保、維修、訓練傳承等可選應用。MKA 是第一個 Domain Pack。
6. **Tenant Solutions** — 租戶版型、欄位、規則、流程、整合 adapter 與必要的專屬 extension。

核心不認識「報價」「8D」「師傅」等產品名詞；Domain Pack 透過版本化 provider、
handler、projector、policy、route 與 UI manifest 接入，不能反向成為平台權威。

---

## 2. 架構總覽

```text
┌──────────────────────────────────────────────────────────────┐
│ Clients                                                       │
│ Web / PWA / Mobile (experimental) / API / Capture UI          │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│ Tenant Experience Composer                                   │
│ capability bootstrap / navigation / module routes / UX state │
└───────────────┬───────────────────────────────┬──────────────┘
                │                               │
┌───────────────▼──────────────┐  ┌─────────────▼──────────────┐
│ Workflow Kernel              │  │ Enterprise Knowledge Kernel │
│ Task / Form / Rule           │  │ QueryPlan / Retrieval        │
│ Approval / Export / Write    │  │ Evidence / Citation / Refusal│
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

### 架構不變量

- Platform 不得直接 import MKA 或其他 Domain Pack internals。
- 所有 tenant-owned 資料、快取、物件、事件與背景任務都必須攜帶 tenant identity。
- 有效權限是 tenant、KB revision、department、source ACL、deny/tombstone、module
  entitlement 與 domain applicability 的交集。
- 解析完成不等於可以回答；低信心、高風險或 SOP 衝突內容必須先 review。
- 每個使用者可見 claim 必須能回到穩定 Evidence locator。
- Sidecar 是 provider／projection，不是 canonical authority；失敗時必須明確降級。
- Pack 可用性由部署能力、租戶 binding 與使用者授權三者共同決定。

---

## 3. 多模態知識模型

```text
SourceAsset
  → immutable AssetRevision
  → DerivedArtifact
  → EvidenceSpan
  → provisional KnowledgeUnit
  → human review / conflict resolution
  → active KnowledgeRelease
  → tenant-scoped retrieval + citation
```

### SourceAsset 與 Artifact

支援的來源類型包括：

- document、spreadsheet、image
- audio、long interview、video
- web page、email、dataset
- connector record、API／external record

常見 DerivedArtifact：

- extracted text、layout page、OCR region、table
- timestamped transcript、speaker segment
- video scene、keyframe、audio event candidate
- procedure、entity、risk、exception candidate

Artifact 必須記錄 provider、provider version、confidence、content hash、quality state
與 evidence locator。舊 `Document` 在相容期仍保留，但不再是新架構唯一身分模型。

### EvidenceSpan

| 輸入 | 定位方式 |
|---|---|
| 文件 | page、section、bbox |
| 表格 | worksheet、table、row、column、cell range |
| 圖片 | bbox、region label |
| 音訊 | start/end time、speaker |
| 影片 | start/end time、frame、bbox、track |
| Connector／API | source system、record id、field path |

---

## 4. 統一 Ingestion Fabric

```text
來源加入或擷取
→ tenant／ACL／資料分類 envelope
→ immutable asset revision
→ malware／媒體與容量驗證
→ capability routing
→ parser／OCR／ASR／影音 provider
→ derived artifacts
→ quality／readiness assessment
→ 必要時人工覆核
→ knowledge projection
→ publication gate
→ active index
```

Capability Router 不只看副檔名，也會考量 media type、內容 sniffing、頁數／時長／
解析度、digital／scanned、語言、表格密度、租戶資料政策、provider availability、
成本與延遲預算。

### 影片知識管線

```text
影片匯入、SHA-256、ACL 與權限標記
→ 音訊／影像分離
→ ASR、說話者能力與時間碼
→ 鏡頭切分、關鍵幀、OCR
→ 動作、設備狀態與異常聲音候選
→ 跨模態時間軸對齊
→ 步驟、條件、判斷規則、風險、例外與禁止動作
→ 人員覆核與正式 SOP 衝突檢查
→ 發布為可搜尋、可引用、可版本化的 Knowledge Unit
```

內建能力採保守、證據導向候選；沒有專業視覺動作、語意異音或高品質 diarization
provider 時會標示 unavailable／candidate，不會把啟發式結果包裝成確定診斷。

---

## 5. Domain Packs 與 MKA

### Pack 啟用模型

```text
deployment capability available
AND tenant entitlement / TenantModuleBinding enabled
AND user authorization allows
```

Pack 透過 composition root 貢獻：

- Knowledge Providers／Projectors
- Task handlers／workflow rules
- permissions／review providers
- API routes／Celery tasks
- frontend route、navigation 與 workspace manifests

停用 Pack 後，API、worker contribution、retrieval、navigation、route、workspace 與 action
必須一起 fail-closed；不為不同租戶維護不同 core branch。

### MKA：第一個製造業 Domain Pack

目前保留的製造業應用包括：

- 職能動態工作台與兼任職能切換
- 規格／SOP 查詢與設備場景限定
- 語音開單、掃碼、表單、簽核與匯出
- 異常回報、交接班、設備維修、品質 8D
- 師傅訪談、知識卡、SOP 衝突與新人訓練
- ERP／CRM／MES 寫入護欄與 rollback audit

MKA 不再是 Enclave Base 的硬依賴，而是可按部署與租戶需求啟用的 Pack。

---

## 6. Web 體驗與主要路由

前端由 `/experience/bootstrap` 回傳 deployment capabilities、tenant bindings、user
capabilities、job role 與 UI manifests，再共同組裝 navigation、route、default home
與 workspace cards。前端隱藏只負責 UX，後端仍是安全權威。

| 工作區 | Canonical route | 說明 |
|---|---|---|
| 總覽 | `/overview` | 租戶知識營運、待處理事項與應用入口 |
| 問答 | `/ask` | 有證據的企業知識問答與 evidence drawer |
| 所有資產 | `/knowledge/assets` | 文件、表格、圖片、音訊、影片等統一 Asset Library |
| 新增知識 | `/knowledge/new` | 上傳／拍攝、網址、外部紀錄的統一 Intake |
| 已發布知識 | `/knowledge/wiki` | 已核准、可引用的知識頁 |
| 來源與整合 | `/knowledge/sources` | 上傳、NAS 與可用 Connector |
| 待審核 | `/knowledge/review` | 跨來源 Review Workspace |
| 品質與版本 | `/knowledge/quality` | 失敗、版本、權威與保鮮狀態 |
| 現場作業 | `/job` | 由 Domain Pack 與職能 manifest 動態提供 |
| 師傅經驗 | `/knowhow` | Pack route；作者權限另行驗證 |
| 管理 | `/governance/*` | 組織、部門、稽核、問答洞察 |
| 系統 | `/system/*` | 能力目錄、租戶管理、健康、備份與部署資訊 |

舊 `/documents`、`/audit`、`/query-analytics` 等路徑仍保留 telemetry 與相容轉址。
實際移除必須滿足逐租戶 30 天零流量、公告、disable 與 rollback drill。

---

## 7. 主要程式目錄

| 路徑 | 用途 |
|---|---|
| `app/platform/` | Assets、Knowledge Provider、Ingestion、Pack 與 deprecation 平台契約 |
| `app/ingestion/` | 核心 ingestion adapters 與影片 knowledge provider |
| `app/composition/` | Packs、Knowledge、Ingestion、Multimodal 與 surface composition root |
| `app/packs/` | 可選 Domain Packs；目前包含 MKA manifest、API、permissions、review 與 provider |
| `app/api/v1/endpoints/knowledge_assets.py` | media-neutral Asset Library 與統一 Intake API |
| `app/api/v1/endpoints/review_items.py` | 跨 core／Pack 的統一人工審核 API |
| `app/api/v1/endpoints/video_assets.py` | 影片匯入、時間軸、媒體存取與 artifact review API |
| `app/services/` | 既有服務與遷移期 compatibility implementations |
| `app/tasks/` | 文件、音訊、影片與 MKA 背景工作 |
| `app/models/asset.py` | Asset、Revision、Artifact、Evidence 與影片覆核模型 |
| `app/models/knowledge_unit.py` | Canonical Knowledge Unit／Release authority |
| `app/models/ingestion.py` | Ingestion Job 與事件生命週期 |
| `frontend/src/modules/` | 前端 Pack route ownership 與 module registry |
| `frontend/src/features/` | 平台級首頁與體驗功能 |
| `frontend/src/pages/knowledge/` | Asset、Intake、Review、Video 與 Knowledge Workspace |
| `alembic/`、`app/db/migrations/` | 單一 Alembic migration 鏈與歷史 migration 相容 |
| `docs/` | 架構、Phase Review、release、runbook、安全與驗收證據 |

---

## 8. 主要 API 面

完整 OpenAPI：`/api/v1/openapi.json`

| 領域 | API |
|---|---|
| 認證與體驗組裝 | `/api/v1/auth/*`、`/api/v1/users/*`、`/api/v1/experience/bootstrap` |
| 統一資產 | `/api/v1/knowledge/assets`、`/status`、`/revisions`、`/events`、`/retry` |
| 統一審核 | `/api/v1/knowledge/review-items` |
| 影片知識 | `/api/v1/media/videos`、`/api/v1/media/video-artifacts/*` |
| 問答與生成 | `/api/v1/chat/*`、`/api/v1/gateway/*`、`/api/v1/generate/*` |
| Connector | `/api/v1/connectors/*` |
| Wiki／Graph | `/api/v1/wiki/*`、`/api/v1/graph/*` |
| MKA Pack | `/api/v1/forms/*`、`/api/v1/knowhow/*`、`/api/v1/approvals/*`、`/api/v1/job-roles/*` |
| 治理與維運 | `/api/v1/audit/*`、`/api/v1/admin/*`、`/api/v1/operations/*` |
| Legacy telemetry | `/api/v1/deprecations/*` |

---

## 9. 本機快速啟動

### 9.1 Docker Compose

```bash
cp .env.example .env
# 設定 SECRET_KEY、FIRST_SUPERUSER_*、POSTGRES_*、REDIS_* 與需要的 provider

docker compose up -d --build
python -m alembic upgrade head
python scripts/initial_data.py
```

預設 Compose 位址：

| 服務 | 位址 |
|---|---|
| Frontend container | `http://127.0.0.1:3001` |
| API container | `http://127.0.0.1:8011` |
| PostgreSQL | `localhost:5435` → container `5432` |
| Redis | `localhost:6380` → container `6379` |

### 9.2 本機開發

```bash
docker compose up -d db redis
python -m alembic upgrade head
python scripts/initial_data.py

python -m uvicorn app.main:app --host 127.0.0.1 --port 8005 --reload
python -m celery -A app.celery_app worker --loglevel=info --pool=solo

cd frontend
npm install
npm run dev
```

Vite 預設使用 `http://127.0.0.1:3000`，並將 `/api` proxy 到
`http://127.0.0.1:8005`。

### 9.3 合成 Demo 租戶

```bash
python scripts/demo_tenant.py seed
python scripts/demo_tenant.py verify
```

六個 passwordless persona 只在 `DEMO_LOGIN_ENABLED=true` 且固定合成租戶驗證通過時
提供。普通客戶部署預設關閉；完整安全邊界見
`docs/runbooks/SYNTHETIC_DEMO_TENANT.md`。

---

## 10. 驗證與 Code Review

```bash
# Backend
python -m pytest tests/ -q
python -m alembic check

# Frontend
cd frontend
npm test -- --run
npm run lint -- --quiet
npm run build
```

架構／發布相關驗證：

```bash
python scripts/knowledge_authority_gate.py
python scripts/verify_modular_rollback.py
python scripts/audit_legacy_surfaces.py
python scripts/generate_legacy_removal_report.py
python scripts/preflight_check.py --profile lite
bash scripts/verify_deployment.sh
```

每個完整 phase 必須先完成獨立 Code Review，才可進入下一階段；相關紀錄集中於
`docs/PHASE_*_CODE_REVIEW.md`。

---

## 11. 部署現況與發布流程

### 正式站現況

- [https://kachu.tw](https://kachu.tw) 已在正式環境與正式網域提供服務；目前 release 為 `rta-i10-a67e937`，source commit 為 `a67e93743f834f016dafa9b50f95590b00d2ea27`，schema head 為 `input_i10_confidence_001`。
- Deployment manifest `dm-52ca7b60c7a535c183ef7903` 與 route hash `5af2bf671476e71a40b148d374217000cf5271c648b6a96e7632e5ddb525b69f` 已完成 backend／frontend release parity；目前 release 的 service health、TLS、正式登入與第一租戶瀏覽器驗收 PASS。Provider probe 已在 current-release web 容器執行，7／7 PASS 且 `release_bound=true`。
- 八策股份有限公司已以受控 Pilot 方式建立正式租戶、管理部與兩位具名帳號；陳宥竹與李永仁目前皆為 owner。兩個帳號的 tenant scope、部門、正式環境、Ask 與文件清單已完成驗證；場景應用未自動開通，`tenant_module_bindings=0`。
- 企業使用者由 [https://kachu.tw/login?mode=enterprise](https://kachu.tw/login?mode=enterprise) 以公司電子郵件與密碼登入。登入後頁首顯示租戶名稱；「我的帳號」會顯示公司、部門、正式／Demo 環境與帳號權限，並提供本人密碼變更。密碼更新後會清除本次登入並要求重新登入。
- 正式工作區不再依 Owner、HR、Viewer 等職稱切換成不同產品介面；所有人使用同一套 Input＋Knowledge／Ask 核心，安全角色只決定可執行的能力，租戶啟用的場景模組才決定額外功能是否出現。
- 過期或無效的 bearer token 現在以 HTTP 401 要求重新驗證；正式站已用原失敗 session 驗證能自動清除舊登入並回到 `/login`，重新進入公司管理 Demo 後 `/overview` 正常載入且 console error 為 0。
- 應用內瀏覽器已以正式合成租戶驗證登入、Overview、多元 Input、現場擷取、Asset Library、來源整合及 Input Pilot；桌面與 390×844 窄螢幕無橫向溢位，console error／warning 為 0。驗收未新增 Pilot、未上傳檔案、未寫入正式資料。
- Production burst 執行完整 29 項時，有 10 項因既定 `RATE_LIMIT_GLOBAL_PER_IP=200` 回傳 HTTP 429；rate-limit window 後以正常速率重跑 targeted suites 8／8 PASS。此結果證明限流正常生效，不被記錄為 production 全套 29／29 PASS。
- P1 CI／supply-chain provenance、P2 staging FORCE-RLS full regression 均 PASS；production application role 已切為 `enclave_app`，111 張 tenant table 全數 FORCE RLS，post-cutover 攻擊矩陣 11／11 與 shadow parity PASS。共享式多租戶擴流仍以觀察期、外部滲透與容量證據為 gate。
- P5 live capacity、degradation 與 soak evidence 已正式記錄為 WAIVED／NOT RUN；實體 iPhone／Android、長時間真實媒體、工廠噪音 ASR 與 Mobile Safari media stack 仍是 Commercial GA gate。

Production DB secrets 已分為三檔：`.env.production`（application）、`.env.db-admin`（schema owner／backup）、`.env.maintenance`（audited cross-tenant worker），權限均為 `0600`。`web`／一般 worker 現使用 `enclave_app`，不得取得 admin 或 maintenance credential；跨租戶工作僅由 `enclave_maintenance` 透過 audited bypass 執行。111 張保護表已 FORCE RLS，shadow／canary／rollback 與 production 攻擊 gate 均已通過。

### 最新基線發布順序

1. 建立 DB、object storage 與 deployment image 可驗證備份。
2. 以正式 schema clone 執行 migration upgrade／downgrade／re-upgrade；部署採 stop → owner `migrate` → `provision-db-roles` → up，web 不執行 Alembic。
3. 建置並 pin backend、worker、frontend image identity。
4. 先部署 staging，再以少量 tenant／feature flag canary。
5. 驗證登入、tenant isolation、Asset Intake、processing、Review、retrieval、citation、
   Pack enable／disable 與 legacy redirects。
6. 具備 ffmpeg／ffprobe、malware scanner、Celery、ASR／OCR／embedding provider 後，
   再啟用音訊與影片處理。
7. 通過 production browser smoke 與 rollback rehearsal 後才擴大流量。

部署腳本與 runbook：

- `scripts/deploy_linode.sh`
- `scripts/verify_deployment.sh`
- `docs/release/MODULAR_PLATFORM_UPGRADE_GUIDE.md`
- `docs/runbooks/RLS_AUTHORITY_ROLLOUT.md`
- `docs/runbooks/LEGACY_SURFACE_RETIREMENT.md`

---

## 12. 已知限制與誠信邊界

- 影片管線與治理已完成，不代表跨產業動作辨識、設備診斷或異音分類準確率已證明。
- 正式 provider、實體手機長時間錄音、鎖屏／切換 App、工廠弱網與噪音仍需環境驗收。
- 既有問答 holdout 約 78–79% 是歷史凍結基線，不代表新多模態資料的泛化品質。
- 掃描 OCR、ASR、embedding、外部模型與 Connector 可因部署資源而降級；系統必須明示，
  不得回報假完成。
- 高風險操作不能只依賴 AI narrative；必須引用正式 SOP，並依政策要求主管核准。
- Production 目前為 111 張 RLS-enabled／FORCE-RLS table，application login 為 `enclave_app` 且無 superuser／BYPASSRLS；共享式多租戶擴流仍受觀察期、外部滲透與容量證據約束。
- P5 live capacity／degradation／soak campaign 已標記為 WAIVED／NOT RUN，尚無商用規模與長時間穩定性的 production evidence；首租戶須以配額、併發上限與監控控管風險。
- Legacy routes、schemas 與 durable objects 尚未獲准移除。
- 外部滲透、法律／模型商用授權、客戶現場 DR 與正式資料處理政策仍需人工簽核。
- Mobile Expo 是 experimental 路徑；Web／PWA 為目前主要產品介面。

---

## 13. 重要文件

| 文件 | 用途 |
|---|---|
| `docs/MODULAR_MULTIMODAL_KNOWLEDGE_PLATFORM_ARCHITECTURE.md` | 目標架構、依賴規則與 Phase B–G |
| `docs/INPUT_PLATFORM_CAPABILITY_MAP_AND_IMPLEMENTATION_PLAN.md` | Input 平台現況、能力差距、驗收指標與 I0–I8 實作／Code Review 計畫 |
| `docs/APPLICATION_DECOUPLING_IMPLEMENTATION_PLAN_2026-08-29.md` | 核心／Workflow／應用層 A0–A8 脫鉤實作計畫與完成狀態 |
| `docs/PHASE_APPLICATION_A8_PHYSICAL_REMOVAL_FINAL_CODE_REVIEW_2026-08-29.md` | 四個應用物理排除矩陣、全量測試、瀏覽器驗收與最終 Code Review |
| `docs/PHASE_INPUT_I0_CONTRACT_EVIDENCE_CODE_REVIEW_2026-08-29.md` | Input I0 capability contract、sealed evidence、telemetry baseline 與最終 PASS Review |
| `docs/ARCHITECTURE_AUTHORITY_AND_UIUX_REFACTOR_PLAN.md` | Phase H–M 權威收斂與 UI/UX 計畫 |
| `docs/UIUX_EXPERIENCE_CONVERGENCE_PLAN.md` | UX-A–UX-D 體驗收斂計畫 |
| `docs/FINAL_MODULAR_PLATFORM_CODE_REVIEW.md` | Phase B–G 與影片 F1–F3 最終審查 |
| `docs/FINAL_AUTHORITY_AND_UIUX_CODE_REVIEW.md` | Phase H–M 最終審查與 legacy HOLD |
| `docs/FINAL_UIUX_EXPERIENCE_CONVERGENCE_CODE_REVIEW.md` | UI/UX 最終審查 |
| `docs/UIUX_BROWSER_ACCEPTANCE_2026-08-27.md` | 最新隔離環境瀏覽器驗收 |
| `docs/PRODUCTION_BROWSER_ACCEPTANCE_2026-08-27.md` | 正式網域驗收與目前 release parity 判定 |
| `docs/INTERNAL_PRODUCTIZATION_COMPLETION_PLAN.md` | 無須等待客戶或第三方即可完成的 P0–P8 產品化閉環 |
| `docs/PHASE_P0_RELEASE_PARITY_CODE_REVIEW.md` | Release identity、schema／route parity 與 production gate 審查 |
| `docs/P5_CAPACITY_MODEL.md` | P5 三種資源 profile、SLO、成本與穩定性 gate |
| `docs/runbooks/P5_CAMPAIGN.md` | P5 隔離環境完整執行順序與 evidence 組裝程序 |
| `docs/decisions/P5_LIVE_VALIDATION_WAIVER_2026-08-28.md` | P5 live validation 豁免範圍、已知風險與補做條件 |
| `docs/reports/P6_UIUX_DEVICE_CODE_REVIEW_2026-08-28.md` | P6 UI／UX、瀏覽器與裝置軟體 gate 審查 |
| `docs/release/MODULAR_PLATFORM_UPGRADE_GUIDE.md` | 升級與相容發布指南 |
| `docs/runbooks/SYNTHETIC_DEMO_TENANT.md` | 六 persona Demo 安全邊界 |
| `docs/runbooks/RLS_AUTHORITY_ROLLOUT.md` | RLS／authority rollout |
| `docs/runbooks/LEGACY_SURFACE_RETIREMENT.md` | Legacy observe、warn、disable、remove gate |
| `docs/CAPABILITY_CLAIMS.md` | 能力宣稱與價值證明邊界 |
| `docs/PIPELINE_STRENGTH_MAP.md` | 問答與資料管線強弱地圖 |

---

## 14. 版本敘事

| 稱呼 | 含義 |
|---|---|
| Enclave 1.x（歷史） | 文件庫、聊天、生成與 Agent 監控 |
| Enclave 2.0（歷史部署基線） | Control Plane、Triple Injection、UI 2.0 與 MKA 垂直功能；已由模組化多模態平台 production release 取代 |
| **模組化多模態平台（目前 production）** | 多租戶＋Knowledge Kernel＋Ingestion Fabric＋Workflow Kernel＋可選 Domain Packs；`kachu.tw` 已部署 `rta-i10-a67e937` 並完成 release parity、service health、TLS、least-privilege DB role、111/111 FORCE RLS、第一租戶 current-release 瀏覽器驗收與 Provider 7/7；語意品質仍須以獨立人工 truth corpus 驗收 |
| Controlled Paid Pilot（目前可進行） | 以限定租戶、單一場景、保守配額、客戶自有驗收集與人工治理開始導入；是否共用資料庫依觀察期與風險分級決定 |
| Staging／Canary（持續 gate） | FORCE RLS 觀察、真實裝置、live capacity／soak、provider、rollback 與跨租戶攻擊持續驗證 |
| Enclave GA（未來） | 依實際商業範圍另行決定；外部滲透、法律、真機與真人活動不回寫為開發完成 Gate |

---

## 授權與商用聲明

程式授權見 `LICENSE`／NOTICE。模型權重、第三方 SaaS、開源依賴、資料跨境、錄音／
錄影同意與保存政策必須依實際部署另行完成法律與安全審查；本 README 不構成合規保證。
