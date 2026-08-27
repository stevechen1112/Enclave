# Enclave 第二階段：架構權威收斂與 UI/UX 重構計畫

**文件狀態**：Approved implementation baseline
**建立日期**：2026-08-27
**前置基線**：Phase B–G、影片 F1–F3
**執行原則**：每個完整 Phase 必須依序完成設計、實作、測試、Code Review、修正與 Gate，通過後才進入下一階段。

---

## 1. 決策摘要

第一階段已建立正確的 modular-monolith 骨架，但目前仍是過渡態：`SourceAsset` 已是新輸入的 canonical identity，主要文件 read path 仍由 `Document` 承擔；文件、影片與 know-how 雖可共同檢索，尚未使用同一個版本化 KnowledgeUnit 發布權威；MKA Pack 已控制 provider、descriptor 與 UI manifest，但大量 API 仍由主 router 靜態掛載；產品 UI 仍以文件與製造現場為主要心智模型。

第二階段不推倒重寫。目標是完成下列四個收斂：

1. **資料權威收斂**：所有媒體與 domain knowledge 都能投影為版本化、具 ACL、可發布的 KnowledgeUnit。
2. **產品模組收斂**：Pack 擁有自己的 API、worker、projector、permission 與 UI contribution；平台只組裝公開契約。
3. **產品入口收斂**：使用者以「加入公司知識」為入口，不必先判斷文件、圖片、錄音或影片應進哪個功能。
4. **治理體驗收斂**：所有來源共用 Asset Library、Review Inbox、Evidence Workspace、版本與發布語意。

完成後的產品結構：

```text
Multi-tenant Control Plane
  ├─ identity / tenant / ACL / RLS / audit / quota / entitlement
  └─ Experience Composer

Enterprise Knowledge Kernel
  ├─ SourceAsset / AssetRevision / DerivedArtifact / EvidenceSpan
  ├─ KnowledgeUnit / KnowledgeUnitRevision / ReleaseMembership
  └─ retrieval / citation / refusal / feedback / freshness

Multimodal Ingestion Fabric
  ├─ upload / capture / connector / API
  └─ capability-routed adapters and governed jobs

Workflow Kernel
  └─ task / form / rule / approval / export / write guardrail

Domain Packs
  └─ API / worker / projector / provider / policy / UI module
```

---

## 2. 不變量

### 2.1 多租戶與 ACL

所有 tenant-owned source、artifact、knowledge unit、release、job、event、cache、object key 與 telemetry 均必須帶 tenant identity。任何可讀知識都必須同時滿足：

```text
tenant match
AND subject/role/group/department policy
AND source ACL snapshot
AND active release membership
AND not tombstoned/denied
AND module entitlement and domain applicability
```

禁止以「同租戶」取代完整 source ACL。所有 provider output 必須在 registry boundary 再次驗證 tenant、release 與 visibility。

### 2.2 發布權威

- Parsing completed 不等於 answer-ready。
- DerivedArtifact 不直接等於正式知識。
- 人工核准只建立不可變 KnowledgeUnitRevision；必須加入 active release 才能回答。
- 文件、表格、圖片、音訊、影片與 domain pack knowledge 使用相同 release membership 語意。
- explicit KB revision scope 不得靜默加入 scope 外的 know-how 或影片程序。

### 2.3 Pack 邊界

- `app/platform/**` 不 import `app/packs/**`。
- Pack 不直接修改主 `api.py` 或中央前端 route switch。
- deployment availability、tenant entitlement、user permission 必須是三個不同欄位與判斷。
- 停用 Pack 後，其 API、worker dispatch、provider、projection、navigation、route 與 workspace 全部 fail-closed。

### 2.4 UX 心智模型

- Base 產品不預設使用者屬於製造現場。
- 使用者先表達目的，例如加入知識、查詢、審核、執行工作；媒體種類是系統處理細節。
- 同一 lifecycle 使用同一組狀態名稱、色彩與動作。
- 技術 provider、sidecar、embedding 與 deployment profile 只出現在系統管理層。

---

## 3. 目標資訊架構

```text
首頁
問答
知識
  ├─ 所有資產
  ├─ 處理中
  ├─ 待審核
  ├─ 已發布知識
  ├─ 來源與整合
  └─ 品質與版本
工作                         ← 只有啟用 Domain Pack 才出現
  └─ tenant-enabled pack workspaces
管理                         ← 依權限顯示
  ├─ 人員與權限
  ├─ 應用與模組
  ├─ 政策與稽核
  └─ 系統與部署
```

全域主要動作為「新增知識」：

```text
上傳檔案 / 拍照 / 錄音 / 錄影 / 貼網址 / 連接來源
  → 格式與能力自動偵測
  → 選擇知識庫、部門、角色、資料分類與保留政策
  → 建立 SourceAsset + AssetRevision + IngestionJob
  → 背景處理與即時狀態
  → Review Inbox
  → Evidence Workspace
  → KnowledgeUnit release
```

---

## 4. Phase H：資料權威與多租戶安全收斂

### H1. Generic Asset ACL

- 建立版本化 `AssetAccessPolicy`／ACL contract，支援 public-to-tenant、owner、role、group、department、KB membership 與 explicit deny。
- 將 Document visibility 的 deny precedence 抽為 Asset visibility PEP；Document compatibility adapter 使用同一 evaluator。
- Video list、media token、review API 與 `ApprovedVideoProcedureProvider` 套用相同 visibility。
- provider registry 對每個 candidate 執行 canonical visibility revalidation，不信任 pack 自行過濾。

### H2. Versioned KnowledgeUnit authority

- 持久化 `KnowledgeUnit` stable identity 與 immutable `KnowledgeUnitRevision`。
- 建立 `KnowledgeUnitReleaseMembership`，連結正式 release／KB revision、unit revision、ACL snapshot、policy revision與適用範圍。
- Document chunks、approved video procedures、approved know-how 先以相容 projector dual-write。
- Retrieval 先 dual-read 比對，再以 feature flag 切換到 active KnowledgeUnit release；禁止未發布 artifact 直接進回答。
- citation 保留 source asset、source revision、artifact、evidence span 與 knowledge unit revision 全鏈路。

### H3. RLS readiness

- 將新表納入 RLS policy、tenant composite FK 與 live isolation tests。
- 補齊 production environment contract、shadow mismatch report、專用非-superuser DB role 與回滾程序。
- 本 Phase 不在沒有 14 天 shadow 證據時擅自開啟 FORCE RLS；完成可執行 rollout gate，而非偽造時間條件。

### Phase H Gate

- 跨 tenant、department、group、explicit deny、tombstone、KB revision 與 module entitlement pairwise tests。
- 影片與 know-how 不得繞過 source ACL 或 explicit revision scope。
- legacy retrieval 與 KnowledgeUnit dual-read sealed comparison 無未解釋差異。
- migration upgrade／downgrade／re-upgrade、schema drift、RLS live attack tests 通過。
- 獨立文件：`docs/PHASE_H_AUTHORITY_CONVERGENCE_CODE_REVIEW.md`。

---

## 5. Phase I：Pack 全表面模組化

### 實作

- Pack manifest 新增 API router、Celery task、permission resolver、lifecycle hook 與 frontend bundle contribution。
- 主 API composition root 只掛載 deployed packs；相容路徑由 pack 自己宣告。
- 將現有 113 個 MKA endpoints 依 bounded context 搬入 MKA pack router composition，保留 URL contract。
- 將 `ProductModule`、`PackRegistry`、`TenantModuleBinding` 與 sidecar binding 統一為一個 Product Capability Catalog，但保留 deployment／entitlement／runtime health 三個不同狀態。
- `/experience/bootstrap` 改為純讀；seed 與 tenant provisioning 移至 migration、tenant setup service 或明確 admin command。
- frontend pack 由自己的 bundle export route/navigation/workspace descriptor；中央 registry 不再列舉 MKA route keys。

### Phase I Gate

- 關閉 MKA 時 API route inventory、worker registry、provider、projector、UI routes 與 navigation 均不存在或一致回傳 module-disabled。
- Base-only deployment 可啟動、migration、登入、上傳、檢索與問答。
- bootstrap GET 無 DB mutation test。
- URL compatibility 與 telemetry tests 通過。
- 獨立文件：`docs/PHASE_I_PACK_SURFACE_CODE_REVIEW.md`。

---

## 6. Phase J：統一 Knowledge Intake 與 Asset Library

### Backend

- 建立單一 `/knowledge/assets` API：create、list、detail、revision、status、retry、tombstone。
- create request 支援 multipart upload、capture manifest、URL、connector record 與 API record。
- 媒體型態只決定 adapter selection，不決定產品 endpoint。
- 提供 capability plan、policy rejection、quota、malware、hash dedupe 與 idempotency 的共同回應。
- 舊 `/documents`、`/media/videos`、capture APIs 暫時作 compatibility adapters。

### Frontend

- 全域「新增知識」入口與 mobile capture sheet。
- 單一 Asset Library，依類型、來源、狀態、部門、資料分類、更新日與發布狀態篩選。
- 通用 Asset Detail shell；PDF、table、image、audio、video viewer 以 renderer registry 插入。
- 統一 processing timeline，不讓使用者理解 Celery、ASR、OCR 或 sidecar 名稱。

### Phase J Gate

- PDF、XLSX、CSV、圖片、音訊、影片、URL 與 connector record contract tests。
- 同 hash、重試、部分失敗、超限、惡意檔案、離線恢復與取消流程。
- desktop、tablet、mobile accessibility 與 keyboard flow。
- 舊入口 telemetry 與 rollback route 保留。
- 獨立文件：`docs/PHASE_J_UNIFIED_INTAKE_CODE_REVIEW.md`。

---

## 7. Phase K：統一 Review Inbox 與 Evidence Workspace

### 實作

- 建立通用 `ReviewItem` read model，來源可為文件分類、OCR、表格、transcript、video procedure、know-how、SOP conflict 或 pack-specific decision。
- Review Inbox 依風險、信心、逾期、來源、部門、review policy 與 assignee 分流。
- Evidence Workspace 共用三欄結構：queue、source/evidence viewer、decision panel。
- renderer 支援 page/bbox、row/cell、audio waveform/time、video frame/timeline 與 external record field path。
- 批量核准只允許低風險、政策允許且無 conflict 的同型決策。
- 發布畫面明確顯示 KnowledgeUnit revision、effective date、ACL、SOP precedence 與 rollback target。

### Phase K Gate

- 每種 EvidenceSpan locator 的 deep link、鍵盤操作與 mobile flow。
- 高風險、低信心、未解 SOP 衝突、ACL 缺失、過期 policy 一律 fail-closed。
- reviewer separation-of-duty 與 audit evidence。
- 獨立文件：`docs/PHASE_K_REVIEW_EVIDENCE_CODE_REVIEW.md`。

---

## 8. Phase L：角色化 Shell 與 Domain Pack 體驗

### 實作

- Base capabilities 完全由 bootstrap 提供；前端不再維護需要人工同步的完整 role table。
- bootstrap 尚未完成時使用 skeleton/fail-closed，不短暫顯示 `/job` 或管理入口。
- 將「現場作業」移至 MKA workspace，不再是所有 employee/viewer 的 Base 預設首頁。
- 首頁依角色呈現：個人待辦、知識健康、處理狀態、審核工作與已啟用應用。
- 「應用與模組」以 capability catalog 清楚區分部署能力、租戶授權、runtime health 與使用者權限。
- 拆分大型頁面為 feature controller、query hooks、view model 與可測試 presentational components。

### Phase L Gate

- Base-only、MKA、未來第二個測試 pack 與六 persona 組合。
- route、nav、home、command palette、mobile menu 使用同一 server decision。
- WCAG 2.1 AA 基本對比、焦點、landmark、表單錯誤與螢幕閱讀器標籤。
- 獨立文件：`docs/PHASE_L_EXPERIENCE_COMPOSER_CODE_REVIEW.md`。

---

## 9. Phase M：相容遷移與最終退場

### 實作

- 對舊文件、影片、錄音、review、MKA routes 與 APIs 收集逐租戶 telemetry。
- 提供 bookmark redirect、API deprecation headers、SDK migration notes 與 tenant communication。
- 依 `observe → warn → disable → remove` 執行，不穿越 30 天零流量條件。
- 完成 Document read authority、legacy review queue、中央 MKA route mapping 與重複 module catalog 的退場 PR。

### Phase M Gate

- 所有 active tenants 的零流量證據與 signed removal report。
- backup/restore、DB downgrade compatibility、object-store 不可逆資料清單與 rollback drill。
- 全量 backend/frontend/E2E、sealed retrieval、tenant isolation、accessibility 與 deployment tests。
- 最終文件：`docs/FINAL_AUTHORITY_AND_UIUX_CODE_REVIEW.md`。

---

## 10. API 與 UX 相容策略

- 新 API 先 additive，舊 API 只轉接，不立即刪除。
- 新 UI 先以 feature flag 對測試租戶開啟；舊 route 保持可回滾。
- dual-write 必須記錄 projection parity；dual-read 只用於 shadow comparison，不把兩套結果無條件混入回答。
- migration 不執行大量 tenant backfill；以 resumable、tenant-scoped command 執行並保存 checkpoint。
- 新 renderer 或 pack failure 只隔離該 capability，不拖垮 Base 知識與問答。

---

## 11. 衡量指標

### 架構

- Platform → Pack forbidden imports = 0。
- Base-only static MKA routes = 0。
- 未經 active release 的可檢索 KnowledgeUnit = 0。
- provider visibility revalidation coverage = 100%。
- bootstrap GET writes = 0。

### 產品

- 新增任何支援格式所需主要入口數：1。
- 使用者從上傳到看見處理狀態：不超過 2 個主要動作。
- 待審工作集中率：所有 review type 可由單一 Inbox 抵達。
- 模組關閉後殘留 navigation/route/action = 0。
- 上傳成功率、處理完成率、人工駁回率、SOP 衝突率、time-to-publish 與 evidence deep-link success 可逐租戶觀察。

---

## 12. 風險控制

| 風險 | 控制 |
|---|---|
| KnowledgeUnit 切換造成檢索回歸 | dual-write、shadow dual-read、sealed comparison、feature flag |
| ACL 一般化造成誤放行 | deny precedence、canonical PEP、provider revalidation、pairwise tests |
| Pack API 搬移破壞客戶整合 | URL 不變、router contribution、deprecation telemetry |
| UI 大改影響既有現場流程 | route-level canary、舊入口 redirect、persona E2E |
| RLS 強制後背景工作失敗 | non-superuser live tests、task tenant context、14 天 shadow gate |
| 過度抽象拖慢開發 | 只抽已存在的 document/audio/video/MKA 共通點；renderer 與 adapter 保留專業差異 |

---

## 13. 初始施工邊界（執行前基線）

計畫核准時只允許先進入 Phase H，不同時改導覽或重畫頁面。Phase H 首批
工作依序為：

1. 建立 Asset ACL contract 與 canonical evaluator。
2. 先修正影片 list、content、review、retrieval 的 ACL revalidation。
3. 設計並 migration 持久化 KnowledgeUnit authority。
4. 建立 document/video/know-how dual-write projectors 與 shadow comparison。
5. 完成 RLS readiness gate 與 Phase H Code Review。

這是施工順序的歷史基線；Phase H 通過前，Phase I–M 保持 pending。實際
完成狀態見下一節。

---

## 14. 執行結果（2026-08-27）

| Phase | 結果 | 獨立審查證據 |
|---|---|---|
| H：權威收斂 | PASS | `docs/PHASE_H_AUTHORITY_CONVERGENCE_CODE_REVIEW.md` |
| I：Pack surface | PASS | `docs/PHASE_I_PACK_SURFACE_CODE_REVIEW.md` |
| J：統一 intake | PASS | `docs/PHASE_J_UNIFIED_INTAKE_CODE_REVIEW.md` |
| K：Review／Evidence | PASS | `docs/PHASE_K_REVIEW_EVIDENCE_CODE_REVIEW.md` |
| L：Experience Composer | PASS | `docs/PHASE_L_EXPERIENCE_COMPOSER_CODE_REVIEW.md` |
| M：相容與退場機制 | IMPLEMENTATION PASS；REMOVAL HOLD | `docs/FINAL_AUTHORITY_AND_UIUX_CODE_REVIEW.md` |

Phase M 的 HOLD 是安全閘門的正確結果，不是程式失敗。觀察起日為
2026-08-26，本次審查日為 2026-08-27，尚未滿 30 個完整零流量日；此外
正式 backup/restore 與 N-1 rollback drill 必須由部署環境的具名操作人員
完成。舊 routes、APIs、schema 與 durable objects 因此均未刪除。待每一個
surface 的全 active-tenant 簽章證據及 rollback evidence 通過後，才另開
retirement PR 逐一推進 `warn → disable → remove`。
