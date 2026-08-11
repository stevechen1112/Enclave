# MKA 功能盤點（Feature Inventory）

> 建立日期：2026-08-06
> 盤點方法：直接閱讀原始碼（非憑印象），每項標註證據檔案。

---

## 0. 複檢紀錄（2026-08-06 第二輪）

使用者回報「都補齊了」後逐項複檢。測試狀態：後端 MKA 相關 **160 passed**、`mka_progress_gate.py --all` **27/27 PASS**、前端 **31 passed**、`tsc --noEmit` 乾淨。

### 已補齊（複檢確認 ✅）

| 原缺口 | 證據 |
|--------|------|
| 術語字典 CRUD API | `endpoints/terms.py`（list/search/correct/add/deactivate，已掛載） |
| Module Admin API | `endpoints/job_modules.py`（list/get/enable/disable/config/compatibility/register，已掛載） |
| 音訊保留政策設定 API | `endpoints/audio_policy.py`（GET/PUT policy＋costs 查詢，已掛載） |
| opaque QR 的 DB scene registry | `models/mka.py:373 SceneRegistry`＋`scene_resolver.py:148 _resolve_opaque_db` |
| knowhow lifecycle 接線 | `endpoints/knowhow.py:213-248`（核准→建 review reminder；退休→purge audio） |
| Know-how 編輯 UI＋退休入口 | `KnowhowDetailPage.tsx`（editing 狀態、PATCH、retire 按鈕） |
| 語音上傳防線 | `voice.py` 串流讀取＋25MB 上限＋秒數上限＋成本記錄 |

### 複檢後仍未完成（❌）

| 項目 | 現況證據 |
|------|----------|
| **SOP 衝突偵測未接進送審流程** | `sop_conflict.py` 的 `get_sop_conflict_checker()` 全 repo 無 endpoint 呼叫；knowhow submit 仍不檢查衝突 |
| **Azure／Local STT/TTS 仍是 stub** | `voice_gateway.py:310-337` 四個 provider 仍 raise NotImplementedError；地端語音方案仍缺 |
| **TTS 前端無呼叫** | `services/mka.ts:152` 有 `voiceApi.synthesize`，但全 src 無任何元件呼叫 |
| **P6 企業系統整合** | `write_guardrail.py` 仍無 endpoint／無 ERP/MES adapter |
| **MODULE_ROUTER_ENABLED 仍為 False** | 模組路由器未啟用（`chat.py:207` 的接線不會執行） |

### 新發現：前端死代碼（建了頁面但沒掛路由）⚠️

| 檔案 | 現況 |
|------|------|
| `pages/quote/`（8 個檔：QuoteStart／QuoteFormEditor／QuotePreview／RecognizedFields／SourceDrawer／RuleExplanation／MissingFields） | **App.tsx 無任何 import／route**，`/quote` 仍 redirect 到 `/forms/quote`；整組是死代碼 |
| `pages/incident/`（4 個檔：IncidentCapture／HandoverDraft／SafeChecklist／ScanEquipment） | **App.tsx 無任何 import／route**，死代碼 |
| `components/mka/` 的 ConflictNotice／ApprovalTimeline／OfflineState／TaskCard／RefusalRecovery | 僅自我定義，**無任何已掛路由的頁面使用** |
| terms／job-modules／audio-policy 三個新 API | 前端 `services/mka.ts` **無對應 client**，無管理 UI |

> 結論：後端 API 面補得完整且測試全綠；但「前端有一整組頁面與元件未接路由」以及「sop_conflict／write_guardrail 服務未接線」兩類問題仍在，不能視為全部完成。

---

> 狀態分級：
> - ✅ **完整**：後端 DB 持久化＋API＋前端 UI 全通，可實際操作
> - 🔶 **半套**：程式存在但有明確缺口（未接線／無 UI／無 DB／僅單一 provider）
> - ⛔ **未實作**：stub、NotImplementedError、或計畫有但程式不存在
> - 🧪 **僅測試用**：mock／測試專用，不構成產品功能

---

## 1. 總覽

| 功能域 | 後端 | 前端 | 整體 |
|--------|------|------|------|
| 語音輸入（STT） | ✅ OpenAI provider | ✅ PushToTalk＋TranscriptEditor | ✅（僅 OpenAI 一家） |
| 語音播放（TTS） | ✅ OpenAI provider | ⛔ 前端未接 | 🔶 半套 |
| QR／條碼場景 | 🔶 前綴格式可用，opaque token 無 DB 查詢 | ✅ QrScanner（相機＋手動） | 🔶 半套 |
| 固定表單（報價／採購／異常／交接） | ✅ 4 張表單＋計算＋審核＋匯出 | ✅ FormPage 通用頁 | ✅ |
| 審核收件匣 | ✅ inbox／approve／reject／request-changes | ✅ ApprovalsPage | ✅ |
| 師傅經驗庫（Know-how） | ✅ DB CRUD＋送審＋核准＋退休 | 🔶 無編輯 UI、建立僅標題 | 🔶 半套 |
| 職能模組平台（Module Registry） | 🔶 DB 模型＋服務有，無管理 API | ⛔ 無 UI | 🔶 半套 |
| 術語字典（Term Dictionary） | 🔶 服務有，無 CRUD API | ⛔ 無 UI | 🔶 半套 |
| SOP 衝突偵測 | 🔶 服務有，未接線 | ⛔ | 🔶 半套 |
| 企業系統整合（ERP／MES 寫入） | 🔶 寫入護欄有，無任何 ERP/MES adapter | ⛔ | ⛔ 未實作 |
| PWA（離線／安裝） | — | ✅ manifest＋service worker | ✅ |

---

## 2. 後端 API 端點（已掛載，`app/api/v1/api.py`）

### 2.1 Voice API — `app/api/v1/endpoints/voice.py`

| 端點 | 狀態 | 說明 |
|------|------|------|
| `POST /voice/transcribe` | ✅ | 音訊上傳→STT→draft transcript；有位元組／秒數上限、租戶保留政策（不存文字則落空字串＋`transcript_redacted`）、STT 成本記錄 |
| `POST /voice/sessions/{id}/confirm` | ✅ | 人工確認轉寫與關鍵欄位 |
| `POST /voice/sessions/{id}/resolve` | ✅ | 完成 session；高風險未確認 fail-closed |
| `POST /voice/synthesize` | 🔶 | TTS 端點存在且可用，但**前端沒有任何呼叫**（`services/mka.ts` 的 `voiceApi` 只有 transcribe／confirmTranscript） |

### 2.2 Interaction API — `app/api/v1/endpoints/interaction.py`

| 端點 | 狀態 | 說明 |
|------|------|------|
| `POST /interaction/transcriptions` | 🔶 | 與 `/voice/transcribe` 功能重疊的平行 API；前端走的是 `/voice/*`，此組端點**無前端呼叫** |
| `POST /interaction/sessions` | 🔶 | 同上 |
| `PATCH /interaction/sessions/{id}/transcript` | 🔶 | 同上（內部會用 term dictionary 修正轉寫） |
| `POST /interaction/sessions/{id}/resolve` | 🔶 | 同上 |

### 2.3 Scene API — `app/api/v1/endpoints/scene.py`

| 端點 | 狀態 | 說明 |
|------|------|------|
| `POST /scene/resolve` | 🔶 | 有 prompt-injection 字元阻擋；但 QR **opaque token 的 DB 查詢未實作**（`scene_resolver.py:136-142` 明確註記 "DB lookup not yet implemented"，只回帶標記的空場景）。可用格式僅 `eq:`／`wo:`／`prod:`／`PN:` 前綴與純數字條碼 |

### 2.4 Fixed Form API — `app/api/v1/endpoints/forms.py`

| 端點 | 狀態 | 說明 |
|------|------|------|
| `GET /forms` | ✅ | 列出表單（lazy seeding） |
| `GET /forms/{name}/schema` | ✅ | |
| `POST /forms/{name}/validate` | ✅ | |
| `POST /forms/{name}/instances` | ✅ | 建檔（DB 持久化） |
| `GET/PATCH /forms/instances/{id}` | ✅ | 樂觀鎖 record_version |
| `POST .../calculate` | ✅ | 確定性計算（小計／稅額／總計） |
| `POST .../validate` | ✅ | |
| `POST .../submit` | ✅ | 送審＋產生 ApprovalRequest（冪等鍵） |
| `POST .../export` | ✅ | 同步匯出；`async_export=true` 走 Celery 回 202 |
| `GET .../exports`、`GET .../exports/{i}/download` | ✅ | 非同步匯出列表與串流下載 |

已註冊表單（`app/services/fixed_form.py`）：`quote`（報價）、`purchase_order`（採購）、`incident_report`（異常回報）、`shift_handover`（交接班）。**表單定義寫死在程式碼**，無後台可讓租戶自訂表單。

匯出渲染（`app/services/template_renderer.py`）：PDF（reportlab）、DOCX（python-docx）、XLSX（openpyxl）、MD 皆為**真實產檔**；套件未裝時回明確錯誤而非假成功。

### 2.5 Approval API — `app/api/v1/endpoints/mka_approvals.py`

| 端點 | 狀態 |
|------|------|
| `GET /mka-approvals/inbox`、`GET /{id}` | ✅ |
| `POST /{id}/approve`、`/reject`、`/request-changes` | ✅（不可變快照、版本檢查、冪等） |

### 2.6 Know-how API — `app/api/v1/endpoints/knowhow.py`

| 端點 | 狀態 | 說明 |
|------|------|------|
| `POST /knowhow`、`GET /knowhow`、`GET /{id}` | ✅ | DB 持久化 |
| `PATCH /knowhow/{id}` | 🔶 | 後端可用，**前端未接**（無編輯 UI） |
| `POST /{id}/submit`、`/approve`、`/retire` | ✅ | submit 前端有接；approve 走審核收件匣；**retire 前端無入口** |

### 2.7 計畫要求但不存在的 API 群組

| 計畫項目（§5） | 狀態 |
|----------------|------|
| Module API（§5.4：模組列表／啟停／綁定管理） | ⛔ 無獨立端點；僅 `GET /experience/bootstrap` 唯讀回傳 job_modules |
| Term Dictionary CRUD API | ⛔ 無端點（服務僅在 interaction.py 內部使用） |
| 音訊保留政策設定 API | ⛔ 無端點（政策表存在，但無設定入口，用預設值） |

---

## 3. 後端服務層盤點（`app/services/`）

### 3.1 已接線、真實運作

| 服務 | 說明 |
|------|------|
| `mka_persistence.py`（1135 行） | MKARepository：transcript／form instance／approval／knowhow 的 DB 存取，租戶隔離、樂觀鎖、冪等 |
| `fixed_form.py` | 4 張表單 schema＋確定性計算引擎 |
| `template_renderer.py` | PDF／DOCX／XLSX／MD 真實渲染 |
| `audio_retention.py` | 租戶保留政策 DB 讀寫＋成本記錄 |
| `voice_gateway.py` | STT/TTS 抽象層；**僅 OpenAI provider 可用** |
| `embedding_cache.py` | Redis＋記憶體 fallback 的 embedding 快取 |
| `module_registry.py` | 從 DB 讀 JobModule＋TenantModuleBinding（被 experience/bootstrap 使用） |

### 3.2 存在但未接線（沒有任何 endpoint import）

| 服務 | 狀態 | 說明 |
|------|------|------|
| `sop_conflict.py` | 🔶 未接線 | SOP 衝突偵測邏輯完整，但 knowhow 送審流程**沒有呼叫它**；僅 gate 測試直接驗證 |
| `incident_handover.py` | 🔶 未接線 | IncidentForm／ShiftHandover／TaskAssignment／SafeGuidancePolicy 類別完整，但實際異常／交接走的是 fixed_form 引擎；此檔為**平行實作，無 endpoint 使用** |
| `knowhow_card.py` | 🔶 未接線 | `KnowhowCardManager` 用**記憶體 dict** 存卡（重啟即失）；實際 knowhow API 走 `mka_persistence` DB，此 manager 無人使用 |
| `knowhow_lifecycle.py` | 🔶 未接線 | 音訊 lineage／review reminder／consent，**記憶體儲存**且無 endpoint 呼叫 |
| `module_admin.py` | 🔶 未接線 | 模組註冊／啟停／相容性矩陣服務完整，但**無管理 API** |
| `write_guardrail.py` | 🔶 未接線 | P6 寫入護欄（風險分級、冪等、回滾、audit）邏輯完整，但無 endpoint、無任何 ERP/MES adapter 可執行 |
| `module_router.py` | 🔶 預設關閉 | 7 個預設職能模組寫死在程式碼（非 DB）；`MODULE_ROUTER_ENABLED=False`（預設），僅 `chat.py` 在開啟時使用 |

### 3.3 明確 stub（NotImplementedError）

`voice_gateway.py:308-337`：
- `AzureSTTProvider`／`AzureTTSProvider` → `NotImplementedError`（待真實 Azure 帳號）
- `LocalSTTProvider`／`LocalTTSProvider` → `NotImplementedError`（待本機模型整合）

即：**地端部署目前沒有可用的語音方案**（計畫要求雲端與地端 provider 可替換，介面有、地端實作無）。

### 3.4 背景任務（`app/tasks/mka_tasks.py`）

| 任務 | 狀態 |
|------|------|
| `purge_mka_retention` | ✅ 每日硬刪過期轉寫（Celery beat） |
| `render_form_export` | ✅ 非同步匯出落 StorageBackend |

---

## 4. 前端盤點（`frontend/src/`）

### 4.1 完整可用

| 頁面／元件 | 說明 |
|------------|------|
| `pages/job/JobHomePage.tsx` | 現場首頁：語音、掃碼、4 張工作單入口、經驗庫、問知識庫、待審核提醒 |
| `components/mka/PushToTalk.tsx` | MediaRecorder 真錄音，大按鈕 |
| `components/mka/TranscriptEditor.tsx` | STT 確認與關鍵欄位修正 |
| `components/mka/QrScanner.tsx` | BarcodeDetector 相機掃描＋手動輸入降級（真實功能，非 mock） |
| `components/mka/SceneContextBanner.tsx` | 場景顯示與清除 |
| `pages/forms/FormPage.tsx` | 通用表單頁：填寫→檢查（建檔＋計算＋驗證）→送審→核准後匯出（PDF/DOCX/XLSX/MD 真下載） |
| `pages/approvals/ApprovalsPage.tsx` | 收件匣、快照明細、兩段式核准、退回必填理由 |
| `public/manifest.webmanifest`＋`public/sw.js` | PWA 安裝與離線降級（app shell cache-first、API network-first） |

### 4.2 半套

| 頁面 | 缺口 |
|------|------|
| `pages/knowhow/KnowhowListPage.tsx` | 建立知識卡**只能填標題**（`knowhowApi.create({ title })`），步驟／注意事項等欄位無法在建立時填 |
| `pages/knowhow/KnowhowDetailPage.tsx` | **無編輯 UI**（後端 PATCH 閒置）；只能看＋送審；無退休入口 |

### 4.3 完全沒有 UI 的後端能力

- TTS 語音播放（端點閒置）
- 術語字典管理（無 API 也無 UI）
- 職能模組管理（啟停／綁定，服務閒置）
- 表單定義管理（表單寫死在 `fixed_form.py`）
- 音訊保留政策設定（DB 表用預設值）
- SOP 衝突報告呈現（`conflict_report` 欄位存在但無產生來源）
- 語音用量／成本查詢（`MKATaskCost` 有落庫，無查詢介面）

---

## 5. 功能旗標現況（`.env`）

| 旗標 | 目前值 | 說明 |
|------|--------|------|
| `VOICE_STT_ENABLED` | true | |
| `VOICE_TTS_ENABLED` | true | 但前端未接 |
| `FIXED_FORM_ENABLED` | true | |
| `KNOWHOW_CARD_ENABLED` | true | |
| `MODULE_ROUTER_ENABLED` | **false（預設）** | 模組路由器未啟用 |
| `VOICE_STT_PROVIDER` / `VOICE_TTS_PROVIDER` | openai | 唯一可用 provider |

---

## 6. 與工程計畫 P0–P6 對照

| 階段 | 程式狀態 | 主要缺口 |
|------|----------|----------|
| P0 契約／準確性／研究基線 | ✅ gate 全過 | UX 研究（MKA-UX-*）需真人，不可代勞 |
| P1 PWA／Voice-first／規格 SOP | 🔶 | Azure／Local STT/TTS 未實作；opaque QR 無 DB registry；TTS 前端未接；術語字典無管理面 |
| P2 業務報價助理 | ✅ | 表單定義無後台（寫死 4 張） |
| P3 現場異常／交接 | 🔶 | 表單流程可用，但 `incident_handover.py` 的安全指引政策（SafeGuidancePolicy）未接進回答路徑 |
| P4 職能模組平台化 | 🔶 | DB＋服務有；無管理 API／UI；module_router 預設關閉且模組寫死 |
| P5 Know-how 與知識傳承 | 🔶 | DB 流程（草稿→送審→核准→退休）可用；但衝突偵測、lineage、review reminder 皆未接線；前端無編輯 |
| P6 企業系統整合 | ⛔ | 僅寫入護欄骨架；無任何 ERP／MES／PLM adapter，無 read-only 查詢整合 |

---

## 7. Mock／測試專用（不構成產品功能）

| 位置 | 說明 |
|------|------|
| `app/gateway/adapters/base.py` `MockAdapter` | Phase 1 測試用，未 re-export，不會進生產 |
| `connector_sync.py`／`pipeshub_http.py` 的 `mock_*` | 需明確 `allow_mock=true` 且生產禁止，屬開發降級 |
| 前端 `*.test.tsx` 內的 `vi.mock` | 單元測試正常用法 |

**前端產品程式碼無任何 mock 資料**——所有頁面都打真實 API。

---

## 8. 不可代勞（需真人／真實環境）

引用 `docs/OPEN_GATES.md`：

- 三角色 UX 研究／任務測試（MKA-UX-*）— 需真人訪談
- 真機＋弱網＋噪音 E2E — 需真實手機
- Design Partner UAT — 需真實客戶
- DB migration 在真實環境執行
- 外部滲透／法律簽核

---

## 9. 願景驗收矩陣（Acceptance Matrix）

> 每項必須同時標示 DB／API／UI／runtime／E2E。缺任一項不得標完成。
> 狀態：✅ 有證據 ｜ 🔶 部分 ｜ ⛔ 外部／人工 gate

| 願景能力 | DB | API | UI | Runtime 呼叫鏈 | E2E | 證據 |
|---------|----|-----|----|----------------|-----|------|
| 語音 STT + 專有詞校正 | ✅ interaction_sessions / terms | ✅ `/voice/transcribe` `/terms/*` | ✅ PushToTalk | ✅ `correct_transcript` 主路徑 | 🔶 | `voice.py` + gate `voice_term_call_chain` |
| SceneRegistry opaque QR | ✅ `mka_scene_registry` migration | ✅ `/scene/resolve` `/scene/registry` | ✅ QrScanner | ✅ DB resolve | 🔶 | `mka_p2_vision_platform_001` |
| Scene→表單預填／檢索 | ✅ form_instances.scene_context | ✅ forms create + chat scene | ✅ FormPage / JobHome | ✅ `scene_to_filter_dict` | 🔶 | `scene_scope.py` + chat/forms |
| 職能 JobRole 與指派 | ✅ job_roles / assignments | ✅ `/job-roles*` | ✅ JobHome 切換 | ✅ bootstrap seed | 🔶 | `job_roles.py` |
| 五正式模組平台 | ✅ job_modules + bindings | ✅ `/job-modules` + seed | ✅ ModulesPage 職能區 | ✅ DB ModuleRouter | 🔶 | `mka_module_seed.py` |
| 動態職能工作台 | — | ✅ bootstrap workspace_entries | ✅ JobHomePage | ✅ | 🔶 | 死代碼 `pages/quote|incident` 已刪 |
| 公司 DOCX/XLSX 版型 | ✅ mka_form_templates | ✅ `/forms/templates*` | 🔶 管理 API 可用 | ✅ StorageBackend | ⛔ 需真實客戶檔 | `form_template_service.py` |
| 表單 instance 清單／詳情 | ✅ form_instances | ✅ `/forms/instances` | ✅ FormInstancesPage | ✅ | 🔶 | App routes |
| 願景表單（會議／維修／請款／8D／訓練） | ✅ FormDefinition seed | ✅ schema ensure | ✅ FormPage | ✅ | 🔶 | `fixed_form.py` |
| SOP 衝突（真 Document） | ✅ conflict_report | ✅ knowhow submit | 🔶 詳情顯示 | ✅ Document/Chunk 查詢 | 🔶 | `_run_sop_conflict_check` |
| 訪談→知識卡 | ✅ lineage DB | ✅ `/knowhow/interview/extract` | ✅ InterviewPage | ✅ consent 必填 | 🔶 | `interview.py` |
| ERP/CRM/MES adapter | ✅ write_requests/audits | ✅ `/enterprise/*` | ⛔ | ✅ fail-closed stub | ⛔ 需客戶憑證 | `enterprise_adapters.py` |
| MKA 指標 | ✅ mka_events | ✅ `/mka/metrics/summary` | 🔶 | ✅ | 🔶 | `mka_metrics.py` |
| 防假綠 gate | — | — | — | ✅ 路由＋migration＋呼叫鏈＋可選 live OpenAPI | 🔶 手機／客戶版型人工 | `mka_progress_gate.py` |

### 仍屬人工／外部 gate（不得以 mock 代替）
- 真實客戶 DOCX／XLSX 版型比對驗收
- 業務／現場／主管手機 E2E（弱網／噪音）
- ERP／MES 真實規格與憑證
- Design Partner UAT、真人 UX 研究

---

## 10. 建議後續（外部依賴）

1. **地端 STT/TTS provider**（需先決定本機模型方案）
2. **真實客戶版型檔案上傳驗收**
3. **ERP／MES 連線憑證**
