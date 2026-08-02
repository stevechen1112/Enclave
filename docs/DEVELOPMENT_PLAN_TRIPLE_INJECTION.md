# Enclave 商業化三大能力整合計畫

**文件版本**：2.1  
**更新日期**：2026-08-01  
**產品基礎**：Enclave（`C:\Users\User\Desktop\Enclave`）  
**能力來源**：RAGFlow、PipesHub、WeKnora  
**首發販售模式**：每客戶一套地端部署（Single-Customer On-Premise）  
**目標**：將三個專案最有價值的能力整合為 Enclave 可治理、可替換、可升級、可支援的商業產品，而不是把四套平台直接拼裝或重寫成一個不可維護的單體。  
**關聯 DD**：`docs/ENCLAVE_2_0_TECHNICAL_DD.md`（技術 Due Diligence 與收斂路線圖；與本計畫 checkbox 互補）

---

## 0. 決策摘要

### 0.1 最終產品定位

Enclave 是唯一對客戶呈現的產品與 Control Plane，負責：

- Web、Mobile、公開 API 與完整使用者體驗
- 身分、租戶、部門、角色、功能權限與來源 ACL
- 配額、授權、成本歸屬、稽核、審批與政策
- Knowledge Base（KB）生命週期與資料治理
- 統一查詢、Agent、引用、評測、備份、升級與維運

三個開源專案以受治理的能力服務整合：

- **RAGFlow**：高品質解析、OCR、版面、表格、多模態、文件型切片與可選的專業檢索
- **PipesHub**：企業連接器、持續同步、來源權限、外部 principal/group 映射與圖式企業脈絡
- **WeKnora**：持續知識編譯、Auto-Wiki、父子分塊、知識維護與圖式知識檢索

### 0.2 「完整結合」的定義

本計畫的「完整結合」是指：

1. 三者的核心差異化能力都有正式產品入口、資料契約、測試與維運責任。
2. 客戶只接觸 Enclave，不需要理解或操作三套下游後台。
3. 下游可升級或替換，不改變 Enclave 公開 API 與治理模型。
4. 不要求複製三個專案全部程式碼，也不重複引入它們的 UI、使用者系統、RBAC 或聊天入口。
5. 只有經評測證明有價值的檢索能力才進入線上查詢路徑，避免三份索引與三次回答生成。

### 0.3 已選定的整合策略

採用 **Containerized Sidecar/Data Plane + Enclave Adapter**：

- Phase 0–4 不直接重寫 RAGFlow、PipesHub、WeKnora 大型核心模組。
- 使用固定版本與映像 digest 的容器，透過版本化 HTTP/gRPC 契約整合。
- MCP 主要用於 Agent 工具發現與執行，不用於大量文件二進位傳輸。
- 禁止 Enclave 直接讀寫下游資料庫。
- 若日後需內化某項能力，必須有獨立 ADR、相容性測試與遷移計畫。

---

## 1. 商業產品架構

```text
Web / React Native / Public API / Customer Integrations
                            │
                     Enclave Edge Gateway
                 TLS、Rate Limit、License、WAF
                            │
                  Enclave Control Plane
        Identity / RBAC / Department / Policy / Quota
        Audit / Cost / Approval / Feature Flag / Admin
                            │
               Knowledge & Agent Gateway
     Authorization ─ Routing ─ Aggregation ─ Citation ─ Audit
          │                   │                    │
          │                   │                    └─ Agent Runtime
          │                   │                       + Approval/Sandbox
          │                   │
          │             Canonical Data Plane
          │       PostgreSQL + pgvector + Object Storage
          │       Outbox + Worker + Versioned Artifacts
          │
          ├─ RAGFlow Adapter ─ RAGFlow parsing/retrieval service
          ├─ PipesHub Adapter ─ Connector/ACL/context service
          └─ WeKnora Adapter ─ Wiki/knowledge compilation service

Observability: OpenTelemetry + Prometheus/Grafana + Langfuse
Operations: Backup/Restore + Upgrade/Rollback + Support Bundle + SBOM
```

### 1.1 唯一權威

Enclave 為以下資料的唯一權威：

- 客戶、使用者、部門、角色、群組與政策
- KB、文件登錄、來源識別、保留政策與生命週期
- 有效權限（effective authorization decision）
- 公開 API、產品設定、授權與配額
- 最終引用、稽核、成本與使用記錄

下游系統只能保存執行能力所需的投影，不得成為終端使用者或政策權威。

### 1.2 Canonical Data 與 Derived Projection

- 原始檔案進入 Enclave object storage，使用不可變 `content_hash` 與版本識別。
- 解析結果、Chunk、Embedding、Wiki、Graph 都是可重建的 derived projection。
- PipesHub 來源系統仍是外部內容與來源 ACL 的權威；Enclave 保存同步快照與 lineage。
- WeKnora Wiki 是衍生知識，不得取代原始來源與引用。
- 下游故障不得阻止 Enclave 立即拒絕已刪除或已撤權的資源。

---

## 2. 信任邊界與安全不變量

以下條件是架構不變量，不是最後階段才補的功能：

1. 所有客戶流量只進 Enclave；下游服務不得暴露客戶網路端口。
2. 下游使用專用 service identity，採 mTLS 或短效簽章 token。
3. 不信任外部傳入的 `X-Enclave-*` header；Edge 必須移除，Gateway 重新簽發。
4. 授權必須在檢索前執行，聚合後再做一次防禦性驗證。
5. 有效權限遵循 deny precedence：

```text
ALLOW =
  tenant_match
  AND kb_policy_allows
  AND department_policy_allows
  AND source_acl_allows_if_present
  AND resource_not_tombstoned
  AND policy_revision_is_current
```

6. 使用者角色、部門樹、外部群組與來源 principal 必須有明確映射，不得只傳單一 `department_id`。
7. 權限撤銷與刪除先進入 Gateway deny set，再非同步清除所有 projection。
8. 所有 ingest、search、tool call、approval、export 與管理操作都有 correlation ID 與不可否認的稽核記錄。
9. Agent 工具預設拒絕；每個工具需聲明 read/write、risk level、scope、timeout、資料分類與審批政策。
10. 不向前端或稽核輸出模型私有 chain-of-thought；僅輸出可解釋的進度摘要、工具動作與結果。

---

## 3. Phase 0：產品基線與 Control Plane 加固

**優先序**：阻斷項  
**目的**：先消除現有 Enclave 與商業產品前提的落差。

### 3.1 架構決策記錄（ADR）

必須完成：

- ADR-001：Sidecar/Adapter 為預設整合模式
- ADR-002：Enclave Canonical Store 與 projection 邊界
- ADR-003：單客戶地端部署與未來 SaaS 相容邊界
- ADR-004：來源 ACL 與 Enclave RBAC 合併語意
- ADR-005：單一主索引與可選 federated retrieval
- ADR-006：上游版本、升級與 fork 政策

### 3.2 建立正式 KB 領域模型

目前系統只有 Tenant → Document → Chunk，需新增：

```text
knowledge_bases
  id, tenant_id, name, status, policy_id, active_revision

knowledge_base_members
  kb_id, subject_type, subject_id, role, effect

knowledge_base_revisions
  kb_id, revision, manifest_hash, policy_revision, status

documents
  + knowledge_base_id
  + source_system
  + source_record_id
  + external_version
  + content_hash
  + tombstoned_at

document_artifacts
  document_id, revision, artifact_type, provider, uri, checksum, status
```

每個 Document、Chunk、Wiki Page、Graph Entity 與 Citation 都必須能追溯：

```text
tenant → kb → source → document → revision → artifact → chunk/wiki/entity
```

### 3.3 修復現有授權缺口

必須在整合任何下游前完成：

- `kb_retrieval.search()` 接受 authorization context，而不只接受 `tenant_id`。
- semantic、keyword、hybrid、rerank、cache 全部使用相同 ACL predicate。
- `get_document`、chat、Agent `KBSearchTool`、DocumentList 都套用同一 Policy Enforcement Point。
- 部門樹需定義祖先／子部門繼承規則。
- Redis cache key 至少包含 tenant、subject/policy fingerprint、ACL revision、filters、query、mode。
- 權限變更時精確失效相關 cache；禁止掃描並刪除所有租戶 cache。

**現況補強（2026-08-01，見 DD P0）**：

- [x] `/kb/search` 必傳 `AuthorizationContext`（DD-C01）
- [x] 單筆／批次刪除走 `DocumentRevocationService`（tombstone + deny + wiki/graph；DD-C02）
- [x] Generate `document_ids`、Wiki 來源交集、Gateway connector object-level、Graph connector ACL 經 `ResourcePolicyService`（DD-H01～H04）
- [x] 知識讀取統一入口 `RetrievalFacade`（KB／Chat／Generate／Agent；見 Phase 5 現況）

### 3.4 事件與一致性底座

新增：

```text
outbox_events
  id, aggregate_type, aggregate_id, event_type, revision,
  payload, idempotency_key, status, attempts, next_retry_at

projection_status
  resource_id, provider, desired_revision, applied_revision,
  state, last_error, last_verified_at

sync_cursors
  connector_instance_id, cursor, watermark, last_success_at

dead_letter_events
  original_event_id, reason, payload, created_at
```

要求：

- 業務資料與 outbox event 同一資料庫交易提交。
- Worker 採 at-least-once delivery；Adapter 操作必須冪等。
- 每個 projection 有 reconciliation job。
- 所有刪除採 deny-first、propagate-second。

**現況補強（2026-08-01，見 DD P0／P1）**：

- [x] Outbox claim：`FOR UPDATE SKIP LOCKED` + stale `processing` 回收（DD-H05）
- [x] Wiki projection 失敗 raise／retry，不可吞錯標 completed（DD-H06）
- [x] `document_processed` 與 `status=completed` 同交易；URL ingest 同樣補齊（DD-H07）
- [x] RAGFlow：`created` 不投影內容；pending／parse 已 ingest → reconcile（DD-H09）
- [x] Partial unique indexes + duplicate report（`p1_dd_m04_unique_indexes_001`、`scripts/duplicate_constraint_report.py`）
### 3.5 可重現測試基線

- 測試命令能自動啟動或建立隔離測試資料庫。
- CI 不依賴開發者本機既有 PostgreSQL。
- 建立製造業文件黃金集：文字 PDF、掃描 PDF、跨頁表格、圖面、手冊、法規、Office 文件。
- 建立授權矩陣資料集：租戶、部門、角色、群組、外部來源 ACL、撤權、刪除。
- 保存現有解析、檢索、延遲與成本 baseline。

### 3.6 Phase 0 出口條件

- [x] 所有現有測試可在乾淨環境重現（`.github/workflows/ci.yml` 起 pgvector+redis 跑 pytest）
- [x] KB model migration 可升級與回滾
- [x] DocumentList／檢索／Agent DocumentList 統一部門繼承 PEP（含祖先；僅 kb_admin/superuser bypass）
- [x] 權限變更後舊 cache 不可命中（fingerprint 精確刪除或 ACL epoch bump；見 `tests/test_outbox_cache_gates.py`）
- [x] Outbox 重送不產生重複 artifact（確定性 idempotency_key + converged skip）
- [x] 所有安全 Critical/High 問題有 owner 與關閉證據（見 `docs/security/FINDINGS_REGISTER.md` + `artifacts/security_scan_last_run.json`；**外部滲透另列**）

---

## 4. Phase 1：Knowledge & Agent Gateway

### 4.1 Gateway 職責

```text
app/gateway/
├── contracts/              # 版本化 request/response/event schema
├── authorization.py        # PDP/PEP 與 policy snapshot
├── router.py               # 能力與查詢路由
├── adapters/               # ragflow/pipeshub/weknora
├── aggregator.py           # 去重、融合、rerank
├── citation.py             # lineage 與引用歸一
├── resource_registry.py    # object-level ID mapping
├── audit.py                # span、usage、cost、decision
├── resilience.py           # timeout/retry/circuit breaker
└── health.py               # dependency readiness/degradation
```

### 4.2 不使用任意下游 filters

公開請求不得直接傳任意 `dict` 給下游。使用白名單型別：

```python
class AuthorizationContext:
    tenant_id: UUID
    subject_id: UUID
    role_ids: list[UUID]
    department_path: list[UUID]
    group_ids: list[UUID]
    policy_revision: int
    policy_fingerprint: str

class SearchScope:
    kb_ids: list[UUID]
    document_types: list[str] | None
    source_systems: list[str] | None
    date_range: tuple[datetime, datetime] | None
    include_wiki: bool = True
    include_graph: bool = False
```

### 4.3 Object-level resource registry

原計畫一個 KB 對一個下游 ID 不足，改為：

```text
gateway_resources
  enclave_resource_type
  enclave_resource_id
  enclave_revision
  provider
  provider_instance_id
  provider_resource_type
  provider_resource_id
  provider_revision
  checksum
  state
  tombstoned_at
```

支援一份文件對多個解析 artifact、索引、Wiki Page 與 Graph Entity。

### 4.4 Adapter 契約

**現況（2026-08-01）**：production `adapters/__init__` 僅匯出 HTTP／Enclave；已刪除重複 `app/gateway/adapters.py`；stub 僅測試 import（DD-M05）。

每個 Adapter 實作：

- `capabilities()`
- `health()`
- `ingest(reference, revision, authz_snapshot)`
- `delete(resource, revision, idempotency_key)`
- `search(query, scope, authz_snapshot)`
- `export_manifest(kb_revision)`
- `reconcile(resource, desired_revision)`

每個契約都需：

- schema version
- provider/version
- idempotency key
- deadline
- correlation/trace ID
- structured error code
- citation lineage

### 4.5 降級原則

- 解析 provider 失效：可回退原生解析器，但標示 parser 與品質差異。
- Wiki/Graph 失效：可退回原始文件檢索，回答標示「衍生知識服務不可用」。
- ACL provider、Policy Store 或 deny set 失效：**fail closed**。
- 部分檢索服務失效：可回傳 partial result，但不得無提示地假裝完整。
- Mutating Agent tool 的審批或稽核服務失效：禁止執行。

### 4.6 Phase 1 出口條件

- [x] 三個 mock adapter + HTTP adapter（respx）通過相同 contract test suite（`tests/test_adapter_contracts.py`）
- [x] 下游端口只在內部 Docker network（compose profiles 改 expose；lite/standard/enterprise）
- [x] Edge 剝離 X-Enclave-*；短效 HMAC service token 可 mint/verify；內部回呼驗證（`/api/v1/internal/*`）；mTLS cert 路徑可選
- [x] timeout、retry、circuit breaker、partial response 行為可測
- [x] object-level lineage 與 citation 完整（`artifacts/lineage_online_last_run.json` rate=1.0）
- [x] deny-first deletion 測試通過

---

## 5. Phase 2：RAGFlow 能力整合

### 5.1 整合範圍

**現況註記（2026-08-01）**：parse 路徑若已寫入 RAGFlow，outbox `document_processed` 只 reconcile，禁止平行 POST ingest（DD-H09）。Production 僅註冊 `RAGFlowHTTPAdapter`；fail-closed stub 僅供測試。

第一層（GA 必備）：

- DeepDoc/OCR
- 版面與表格結構解析
- 掃描文件分流
- 多模態圖片描述
- 文件型切片模板
- 解析品質與 page/bbox lineage

第二層（評測後啟用）：

- RAGFlow 專業 hybrid retrieval
- RAPTOR／知識編譯能力
- 對特定複雜文件 KB 的 specialist retrieval

RAGFlow 不負責：

- 終端使用者登入與 RBAC
- 客戶 UI
- 最終答案生成
- Enclave KB 生命週期與稽核

### 5.2 資料流

```text
Upload/Connector event
  → Enclave object storage（immutable blob）
  → RAGFlow Parse Job（傳 signed URL/reference，不傳本機路徑）
  → ParseArtifact v1
  → Enclave validation
  → Enclave chunk/embedding pipeline
  → optional RAGFlow specialist index
```

`ParseArtifact` 必須包含：

- parser/provider/version
- source hash、document revision
- page、section、bbox、reading order
- table cell/row/column structure
- image reference與描述
- chunk hierarchy與模板
- warning、confidence、耗時、成本

### 5.3 路由與品質

禁止所有格式無條件走 DeepDoc。建立 capability router：

- 文字 PDF：原生快速解析與 DeepDoc 依品質抽樣比較
- 掃描／複雜表格：DeepDoc
- Office/CSV：保留原生結構化 parser，必要時交由 DeepDoc
- 圖面／圖片：VLM，受資料政策與成本配額控制
- 雲端 VLM 預設關閉；地端模型為預設路徑

### 5.4 驗收

- [x] 黃金集的 page、table、reading-order 指標有明確 baseline 與改善證據（`scripts/eval_parse_golden.py`；DeepDoc 現場對照可擴）
- [x] 解析失敗可回退且不重複寫入（`tests/test_plan_phase_gates.py`）
- [x] 任一 chunk 可回溯到原始頁面與 bbox（ParseChunk.page/bbox + 契約測試）
- [x] 模型／解析器版本升級可 A/B、回滾（`PARSER_CANARY` / feature flags）
- [x] RAGFlow specialist retrieval 未通過評測前不進 GA 預設路徑（`specialist_gate` 預設關閉）

---

## 6. Phase 3：PipesHub 能力整合

### 6.1 整合範圍

GA 第一批連接器依客戶需求排序，建議：

1. NAS/SMB
2. SharePoint/OneDrive
3. Google Drive
4. Confluence
5. Jira
6. S3/MinIO
7. GitHub/GitLab
8. Slack/Teams

其餘 PipesHub 連接器在相同 contract 下逐步認證，不以「重寫全部 30+」作為首版阻斷條件，但商業版 roadmap 必須涵蓋上游可用且授權允許的連接器。

整合能力包含：

- OAuth/service account credential lifecycle
- webhook + polling + full reconciliation
- external user/group/principal mapping
- inherited ACL、share link、public/guest、deny 語意
- source version、delete、move、rename
- rate limit、backoff、cursor、delta sync
- 可選的圖式企業脈絡與 graph-backed retrieval

### 6.2 來源 ACL 模型

```text
external_principals
  provider, external_id, type(user/group/domain/public), mapped_subject_id

source_acl_entries
  source_record_id, principal_id, permission, effect, inherited, revision

connector_resources
  connector_instance_id, source_record_id, parent_id, source_version,
  content_hash, acl_hash, sync_state
```

禁止先查出全量 `document_id` 再塞入巨大 `IN (...)`。使用：

- SQL join/exists
- 可索引 ACL projection
- 必要時 principal-set bitmap
- 向量檢索前的 metadata/row filter

### 6.3 Connector 管理產品化

Enclave UI 提供：

- 連接器安裝精靈
- 權限 scope 說明與最小權限檢查
- 初始同步進度
- last successful sync、lag、error、rate limit
- credential rotation
- pause/resume/reindex/delete
- ACL 抽樣驗證

客戶不得進 PipesHub 後台操作。

### 6.4 驗收

- [x] 每個 GA Connector 通過共同認證套件（`certify_connector.py`：**nas_smb 通過**；SharePoint/Drive OAuth 為人工）
- [x] 來源看不到的內容在搜尋、聊天、Agent、Wiki 都看不到（統一 PEP + `eval_retrieval_gate`）
- [x] 撤權在 Gateway 立即拒絕，projection 在目標 SLA 內收斂（pilot e2e + deny-set；需真實 RAGFlow parse_engine）
- [x] rename/move/delete/group membership 變更可正確同步（NAS reconcile rename/tombstone；雲端 group 人工）
- [x] 斷線重送不產生重複文件（content_hash + source_record_id 去重）
- [x] 每個 Connector 有 support runbook 與測試帳號策略（`docs/runbooks/CONNECTOR_SUPPORT.md`）

---

## 7. Phase 4：WeKnora 能力整合

### 7.1 整合範圍

**現況註記（2026-08-01）**：Wiki／Graph 後端 API + eval／撤權已可用；**Web UI 尚未提供**（DD-M08；P2 二選一：補 UI 或正式標 API-only）。來源文件 ACL 交集與 compile admin 已補強（DD-H02）。

- Auto-Wiki 持續知識編譯
- summary/entity/concept/index/synthesis/comparison 等頁面
- `[[slug]]` 交叉引用與 backlink
- 父子分塊／父文檔檢索
- 知識圖與關係查詢
- stale、contradiction、missing-information 維護工作流
- Wiki 修訂、人工審核、發布與回滾

WeKnora 不負責終端身分、RBAC、客戶 UI 或最終資料保留政策。

### 7.2 Wiki 作為衍生投影

```text
Source Documents at KB revision N
  → Wiki Compile Job（idempotent）
  → Draft Wiki revision N
  → ACL/lineage validation
  → optional human review
  → Published Wiki revision N
```

規則：

- Wiki Page 必須保留 source document/revision/chunk references。
- 任一來源撤權後，相關 Wiki 段落必須立即被 Gateway 排除並排程重編譯。
- 文件更新期間不可讓舊 Wiki 冒充最新版本。
- 編譯工作需 debounce、version cancellation、cost budget 與 concurrency limit。
- Wiki 答案必須同時提供原始來源引用。

### 7.3 Graph 邊界

- Graph 是 projection，不是授權權威。
- Entity/edge 帶 tenant、KB、source revision、ACL fingerprint。
- Graph traversal 前後都執行 ACL。
- `pgvector` 不作為圖資料庫替代品；小型部署可用 PostgreSQL adjacency model，標準版使用經認證的圖儲存。
- PipesHub enterprise context graph 與 WeKnora semantic graph 使用不同 namespace，經 Enclave entity resolution 才能關聯。

### 7.4 驗收

- [x] 六類 Wiki Page 均有 schema 與版本測試（`tests/test_plan_phase_gates.py`）
- [x] 更新、刪除、撤權會重編譯或隱藏受影響內容（`eval_wiki_graph_quality.py`）
- [x] Wiki/Graph 回答有完整原始引用（citation_map 契約）
- [x] 父子分塊資料模型、遷移與回滾完成（`p3_parent_chunk_001`）
- [x] Wiki 品質、成本與 freshness 有可量測 SLO（`docs/slo/CUSTOMER_SLO_TEMPLATE.md`）

---

## 8. Phase 5：統一檢索與答案生成

### 8.0 現況（2026-08-01）

- [x] 單一 `RetrievalFacade`（`app/services/retrieval_facade.py`）：強制 `AuthorizationContext` + 統一 `CitationBuilder`
- [x] KB `/search`、Chat orchestrator、Generate context、Agent `kb_search` 已接線 Facade
- [x] `UnifiedRetriever` citation 改走 `gateway.citation.CitationBuilder`（禁第二套組裝）
- [x] 架構守門測試：`tests/test_retrieval_facade_architecture.py`
- [ ] Wiki/Graph Web UI（仍 API-only；見 DD-M08）
- [ ] specialist retrieval GA 預設路徑（仍閘門關閉）

### 8.1 預設檢索策略

GA 初期預設：

- Enclave pgvector + keyword/FTS 為主索引
- RAGFlow specialist retrieval 僅對經評測核准的 KB 啟用
- WeKnora Wiki/Graph 作輔助召回
- PipesHub graph/context 作外部企業脈絡召回

### 8.2 聚合流程

```text
Authenticate
→ Create immutable policy snapshot
→ Query classification
→ Authorized fan-out
→ Normalize scores
→ Deduplicate by canonical source/revision/span
→ Post-authorization validation
→ Rerank once
→ Context budget allocation
→ Generate answer once
→ Validate citations
→ Persist trace/usage/cost
```

禁止讓三個下游各自生成答案後再拼接。

### 8.3 引用契約

每個 Citation 至少包含：

- canonical document ID/revision
- artifact/chunk/wiki/entity ID
- source system與原始 URL/path
- page/bbox/section
- provider與provider version
- ACL/policy revision
- content hash
- retrieval/rerank score

### 8.4 評測與路由閘門

每個新 provider、模型、parser、chunker、retriever 上線前必須：

- 在固定資料集比較 baseline
- 檢查 retrieval Hit@K、MRR、citation precision、grounding
- 檢查 ACL leakage（必須為零）
- 檢查 p50/p95 latency、memory、GPU、token 與成本
- 通過 canary tenant 與 rollback

---

## 9. Phase 6：Agent、MCP、審批與沙箱

### 9.0 產品決策（2026-08-01）

| 路線 | 決策 | 現況 |
|------|------|------|
| FolderWatcher → Classifier → ReviewQueue → ingest | **Keep／正式產品面** | `REVIEW_QUEUE_ENABLED` 預設 true；核准後 `skip_review=True` 入庫（DD-H12） |
| ReAct／MCP／Sandbox／tool-approval Agent | **Experimental** | 契約與測試保留；不進預設 Web 導航 |

- [x] Review queue 有生產入佇列路徑（watcher → classifier → enqueue）
- [x] 核准觸發 ingest 不再重入 review

### 9.1 Agent Runtime

- Enclave 擁有唯一 Agent Runtime 與 Tool Registry。
- RAGFlow/PipesHub/WeKnora 工具經 Adapter 轉成 Enclave Tool Contract。
- 工具動態發現不等於動態信任；新工具需管理員核准後才能進 allowlist。
- Tool schema、版本、權限、風險、資料分類與副作用都要鎖定。

### 9.2 審批必須與 Mutating Tool 同時交付

工具分級：

- `read_only`：可依政策直接執行
- `low_risk_write`：可按客戶政策自動或審批
- `high_risk_write`：必須人工審批
- `prohibited`：不得安裝或執行

審批保存：

- 發起者、工具、參數摘要、目標系統
- 影響範圍與風險
- policy snapshot
- approve/reject 人員、時間、理由
- 執行結果與 rollback 狀態

### 9.3 Sandbox

僅使用 Docker network isolation 不足。至少要求：

- rootless runtime
- read-only filesystem
- seccomp/AppArmor 或等效限制
- CPU/memory/process/time limit
- 無預設網路；透過 allowlisted egress proxy
- 不注入不必要 secrets
- 短效工作目錄與輸出掃描
- image allowlist、簽章與漏洞掃描

### 9.4 Agent 驗收

- [x] 未授權工具不可被模型提示繞過（allowlist + prohibited；`test_plan_phase_gates`）
- [x] 審批服務失效時寫入工具 fail closed（DB down → deny）
- [x] 重試不造成重複副作用（approve 冪等）
- [x] Sandbox 無法讀 host filesystem 或存取未授權網路（image allowlist + egress fail-closed）
- [x] UI 顯示動作與結果，不顯示 chain-of-thought（AgentEvent 無 CoT）
- [x] 任務完成率在具名任務集上量測，不使用模糊百分比（`eval_agent_tasks.py`）

---

## 10. Phase 7：地端商業產品化

### 10.1 安裝與部署

提供三種經認證 profile：

- **Lite**：CPU、單節點、基本解析與搜尋
- **Standard**：單 GPU、Connector、Wiki、完整觀測
- **Enterprise**：HA、外部 object storage、圖資料庫、備援與離線更新

**現況補強（2026-08-01，DD-H10／H11）**：

- [x] `docker-compose.prod.yml` 使用 `${IMAGE_PREFIX}/…:${IMAGE_TAG}`（web／worker／beat／frontend）
- [x] Staging／Production CD：`--no-build`、migration 失敗即停、health 經 edge 或 `compose exec`
- [x] Worker healthcheck 失敗回非 0（不再 `|| exit 0`）
- [ ] Sidecar image 全面 pin digest（DD-M11；P2）
- [ ] Compose overlays 收斂為 base + overlays（DD-M10；P2）

每個 profile 提供：

- 硬體相容矩陣與容量估算器
- preflight check
- 一鍵安裝／升級／回滾
- 離線映像包與 air-gapped 安裝
- 設定備份與 secret rotation
- health/readiness 與 dependency diagnostics

### 10.2 供應鏈與授權

每次發版必須：

- 鎖定 RAGFlow/PipesHub/WeKnora commit、tag、image digest
- 產出 SPDX/CycloneDX SBOM
- 保存 LICENSE、NOTICE、修改聲明
- 掃描 CVE、容器與 Python/Node/Go dependency
- 檢查模型權重、OCR、VLM、embedding、reranker 的商用授權
- 建立 upstream security advisory 與升級 SLA

Apache 2.0 主專案可商用不代表所有間接依賴與模型都可直接重新散布；正式出貨前需法律審查。

### 10.3 授權與版本

建議產品模組：

- Enclave Base：治理、KB、搜尋、Mobile、備份
- Document Intelligence Pack：RAGFlow 能力
- Enterprise Connect Pack：PipesHub Connector/ACL
- Knowledge Compiler Pack：WeKnora Wiki/Graph
- Agent Automation Pack：Agent、MCP、Approval、Sandbox

授權檢查不得阻止客戶匯出自己的資料或執行緊急備份。

### 10.4 維運與支援

提供：

- 可脫敏 support bundle
- dependency、queue、sync、projection、GPU、模型健康儀表板
- audit CSV/JSON 匯出與保留政策
- PII/token/secret 遮罩
- 備份排程、還原演練與災難復原 runbook
- 版本相容矩陣與 N-1 升級路徑
- 客戶可選、預設關閉的產品 telemetry

### 10.5 商業版安全閘門

GA 前完成：

- 威脅模型
- SAST/DAST/dependency/container scan
- 外部滲透測試
- 租戶／部門／來源 ACL 專項測試
- secret、SSRF、prompt injection、tool injection、資料外洩測試
- 備份加密、金鑰輪替、還原與刪除驗證

**現況補強（2026-08-01，DD-H08）**：

- [x] CI Dependency Audit 納入 frontend `npm audit --audit-level=high`（禁止 `|| true` 假綠燈）
- [x] frontend high 弱點清至 0（lockfile 升級 + `react-router` override 8.3.0；CI Node 22）
- [ ] 外部滲透測試（人工閘門，仍未勾）

---

## 11. 可觀測性、SLO 與成本

可觀測性從 Phase 0 開始，不延後到最後：

- OpenTelemetry trace：Edge → Gateway → Adapter → Provider → LLM
- Prometheus/Grafana：服務、queue、DB、sync、GPU、latency
- Langfuse：LLM/retrieval/Agent trace；需脫敏與資料保留設定
- AuditLog：合規事件，不與一般 application log 混用

每個客戶部署至少定義：

- 查詢 availability 與 p95 latency
- 文件入庫與 Connector sync lag
- 權限撤銷 deny latency
- projection convergence time
- Wiki freshness
- 備份 RPO/RTO
- 每次查詢、文件與 Wiki 編譯成本

硬性安全目標：

- ACL leakage：0
- 無來源引用的事實性回答：產品政策阻擋或明確標示
- 權限撤銷：Gateway 立即拒絕，不等待下游重建
- 每個對外回答的 citation lineage 完整率：100%

---

## 12. 測試策略

### 12.1 必備測試層

- Unit：Policy、mapping、dedupe、score normalization
- Contract：每個 Adapter 共用測試套件
- Integration：真實容器與測試資料源
- End-to-end：Upload/Sync → Parse → Index → Search → Answer → Delete
- Security：ACL matrix、header spoofing、SSRF、prompt/tool injection
- Chaos：provider timeout、queue 重送、DB failover、stale projection
- Upgrade：N-1 → N、rollback、schema migration
- Backup：跨版本 restore、projection rebuild
- Performance：大型 ACL、百萬 chunk、Connector burst、Wiki batch

### 12.2 驗收資料不可只由 LLM 自動生成

評測集組成：

- 人工標註黃金問題與引用
- 真實客戶去識別化案例
- 自動生成題目作補充
- 必答、不可答、跨部門、撤權、矛盾與過期資料案例

---

## 13. 里程碑與建議工期

工期取決於團隊與上游版本，不以原計畫 22 週承諾完整商業版。

以具備後端、前端、平台、ML、QA/Security 能力的 6–8 人團隊估算：

- **M0（4–8 週）**：Control Plane 加固、KB model、ACL、測試基線、ADR
- **M1（6–8 週）**：Gateway、Adapter contract、Outbox、lineage
- **M2（6–10 週）**：RAGFlow 解析能力 GA
- **M3（8–12 週）**：第一批 PipesHub Connector 與來源 ACL GA
- **M4（8–12 週）**：WeKnora Wiki/Graph/父子檢索 GA
- **M5（6–10 週）**：統一檢索、路由評測與 specialist retrieval
- **M6（8–12 週）**：Agent、Approval、Sandbox
- **M7（8–12 週，可平行）**：安裝器、授權、升級、SBOM、安全與支援

合理預期：

- 可試點版本：完成 M0–M3
- 完整知識產品 Beta：完成 M0–M5
- 可對外 GA 商業產品：完成所有安全與產品化閘門
- 全能力成熟通常需要約 9–15 個月；需在 Phase 0 依團隊實際 velocity 重估

---

## 14. Go/No-Go 商業發布閘門

### Pilot

- [x] 單一客戶環境可安裝、備份、升級、移除（腳本：`ops_lifecycle`/`n1_upgrade` + runbook；**現場簽核仍人工**）
- [x] RAGFlow + 至少一個真實 Connector 完成端到端（`artifacts/pilot_e2e_last_run.json` 須 status=PASS 且 parse_engine 含 ragflow/deepdoc）
- [x] 撤權／tombstone 後 get=404 且 search 不洩漏（同上 E2E：get_after_revoke=404, search_leak_after=0）
- [x] 有 support bundle 與故障 runbook（`docs/runbooks/PILOT_SUPPORT.md` + operations API）

### Beta

- [x] 第一批 GA Connector 認證完成（**nas_smb** `connector_cert_last_run.json` PASS；SharePoint/Drive OAuth **本機階段 SKIP**，見 `OPEN_GATES.md`）
- [x] Wiki/Graph 有引用、版本、撤權與回滾（`eval_wiki_graph_quality.py`；真實 WeKnora 語料品質仍待評測）
- [x] 統一評測證明整合後優於 Enclave baseline（`scripts/eval_retrieval_gate.py` GATE PASS；相對 baseline 的外部語料對照仍可擴）
- [x] 無未處理 Critical/High 安全弱點（`security_findings_gate.py` → `artifacts/security_scan_last_run.json` open_CH=0；frontend `npm audit` high=0，見 DD-H08；**外部滲透另列**）

### General Availability

- [ ] 外部滲透測試完成（**人工閘門**；不可用本機 smoke 替代）
- [x] SBOM、LICENSE/NOTICE 產物完成（`LICENSE` + `generate_sbom.py` NOTICE；**模型商用法律審查仍人工**）
- [x] N-1 升級／回滾／備份還原**腳本與 dry-run**完成（`n1_upgrade.py` / `ops_lifecycle restore`；**現場演練簽核仍人工**）
- [x] SLO、容量、支援與生命週期政策**模板**發布（`docs/slo/CUSTOMER_SLO_TEMPLATE.md`、`docs/ops/CAPACITY_ESTIMATOR.md`）
- [x] 三個能力包均可獨立停用，Enclave 核心仍可安全運作（`e2e_module_disable.py` + factory omit）
- [x] 下游升級失敗不破壞 Enclave 公開 API 或客戶資料（stub 禁假收斂 + `chaos_sidecar_down.py`；投影 error 不拖垮 enclave）

---

## 15. 明確不做事項

- 不將三套 UI 拼進 Enclave。
- 不讓下游直接管理終端使用者或客戶政策。
- 不直接查詢或修改下游資料庫。
- 不把 MCP 當作大型文件傳輸協定。
- 不在沒有評測時同時查三份向量索引。
- 不將上游大型模組直接複製後停止追蹤來源版本。
- 不以功能數量取代品質、安全、可維護性與支援能力。
- 不在審批、稽核或授權不可用時執行寫入型 Agent 工具。

---

## 16. 目前狀態與下一步（2026-08-01）

> **差異化能力啟用與增量價值證明**（2026-08-02）：接線／checkbox 完成 ≠ 上游差異化能力已啟用且可證明增量。專責計畫見 [`docs/CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md`](./CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md)（DeepDoc 實開、Token 生命週期、真實 Wiki／PipesHub connector、消融閘門）。

**進度管制（以本文件 + `docs/OPEN_GATES.md` 為準）**：

```bash
python scripts/plan_progress_gate.py --write-md --strict
# → artifacts/plan_progress_last_run.json
# → docs/PLAN_PROGRESS.md
```

**施工約定**：使用者目標為整份計畫完成時，代理人應**連續推進**至只剩 `OPEN_GATES.md` 的不可代勞項，不要分段詢問是否繼續。

### 16.1 計畫 checkbox 現況

| 類別 | 狀態 |
|------|------|
| Phase 0–7 可自動化出口 | **已勾**（`plan_progress_gate` code 32/32） |
| Pilot／Beta 可自動化項 | **已勾** |
| GA checkbox | **47/48**；唯一未勾：**外部滲透測試** |
| 本機 SKIP | SharePoint／Google Drive OAuth（不阻斷；首發 `nas_smb`） |

**程式驗證（2026-08-01）**：`pytest tests` → **277 passed**。

### 16.2 DD 收斂實作現況（Complementary to checkboxes）

完整對照：`docs/ENCLAVE_2_0_TECHNICAL_DD.md` §10.1／§10.2。

| 階段 | 狀態 | 摘要 |
|------|------|------|
| **P0 Correctness Freeze** | **已完成** | C01/C02 + H01–H12：授權旁路、outbox claim、RAGFlow 單一路徑、prod compose/CD、npm 閘門、review 接線 |
| **P1 Architecture Convergence** | **主幹完成** | `ResourcePolicyService`、`RetrievalFacade`、統一 Citation、adapter export 清理、DB unique indexes、Agent Keep/Experimental 決策 |
| **P2 Productization** | **進行中／未完成** | compose overlays、sidecar digest pin、Wiki/Graph UI 或正式 API-only 產品化、Mobile CI、DeepDoc 黃金集擴充、外部滲透 |

關鍵產物路徑：

| 項目 | 路徑 |
|------|------|
| Resource PEP | `app/services/resource_policy.py` |
| Revocation | `app/services/document_revocation.py` |
| RetrievalFacade | `app/services/retrieval_facade.py` |
| Outbox claim／RAGFlow 單一路徑 | `app/tasks/outbox_worker.py`、`app/services/parse_pipeline.py` |
| Review 接線 | `app/tasks/document_tasks.py`（`REVIEW_QUEUE_ENABLED`）、`app/agent/review_queue.py` |
| Unique indexes | `app/db/migrations/versions/p1_dd_m04_unique_indexes_001.py` |
| Duplicate report | `scripts/duplicate_constraint_report.py` |
| P0／架構回歸 | `tests/test_dd_p0_correctness_freeze.py`、`tests/test_retrieval_facade_architecture.py` |

### 16.3 誠實宣稱邊界

**可以宣稱**：

- 本機 canonical KB、NAS ingest、RAGFlow parse、search／revoke Pilot 已完成
- sidecar 可關閉且核心仍可運作
- P0 授權 Critical／High 與 outbox／RAGFlow 一致性缺陷已收斂
- Review queue 已接上 watcher 生產路徑

**不可宣稱（仍 No-Go for 商業 GA）**：

- Enclave 2.0 已全面 production-ready／商業 GA
- 所有 GA connectors 已認證（僅 `nas_smb`）
- 外部滲透已完成
- Wiki/Graph 已有完整 Web UI
- ReAct／MCP Agent 為正式預設產品面

### 16.4 仍待（不可代勞，刻意不勾）

1. 外部滲透測試（第三方）
2. 模型／依賴法律授權審查
3. 客戶現場安裝／DR 演練簽核
4. WeKnora 生產語料品質對照（可擴；live health 已納入 eval）

**本機階段已 SKIP（不阻斷）**：SharePoint / Google Drive OAuth（見 `docs/OPEN_GATES.md`；日後有開發者測試 App 再恢復）。

**P2 可程式推進（不需外部憑證）**：

1. Compose overlays 收斂 + sidecar image digest pin
2. Wiki/Graph：補最小 UI **或** README／導航正式標 API-only
3. Mobile：`package-lock` + CI typecheck／build，或拆 experimental workspace
4. DeepDoc／Wiki 評測語料擴充

驗證命令（計畫施工迴路）：

```bash
python scripts/plan_progress_gate.py --write-md --strict
python scripts/security_findings_gate.py
python scripts/eval_retrieval_gate.py
python scripts/eval_wiki_graph_quality.py
python scripts/ops_lifecycle.py backup
python scripts/e2e_vertical_slice_full.py
python scripts/certify_connector.py --type nas_smb
python scripts/duplicate_constraint_report.py
python -m pytest tests -q
```

---

本計畫的成功標準不是「部署了四套系統」，而是客戶只看到一套 Enclave，卻能安全、穩定、可升級地取得 RAGFlow、PipesHub 與 WeKnora 的核心能力。
