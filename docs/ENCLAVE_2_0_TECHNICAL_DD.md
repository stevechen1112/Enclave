# Enclave 2.0 技術 Due Diligence（DD）與架構收斂方案

> 文件日期：2026-08-01  
> 評估範圍：`C:\Users\User\Desktop\Enclave`  
> 評估性質：原始碼、部署、測試、artifact 與產品表面之技術 DD  
> 本文件不等同外部滲透測試、法律意見或正式生產簽核  
> **P0 Correctness Freeze 實作更新：2026-08-01（見 §10.1）**

---

## 1. 執行摘要

### 1.1 最終判定

Enclave 2.0 **不是單純把四套系統胡亂拼接**。它已形成可辨識的核心架構：

- Enclave 掌握租戶、身分、部門、授權、文件生命週期與 canonical pgvector index。
- RAGFlow、PipesHub、WeKnora 透過 adapter／outbox 以可關閉 sidecar 接入。
- NAS → RAGFlow → search → revoke 的本機 Pilot 路徑已實跑成功。
- 全量後端測試（P0/P1 收斂後）：**277 passed**（DD 初評時為 260；P0 後曾為 270）。
- Web production build 成功；frontend `npm audit --audit-level=high`：0。

#### DD 初評時發現的高風險（歷史快照；多數已於 P0/P1 關閉）

當時判定會讓系統長期變成拼裝車的風險如下（**現況見 §10.1／§10.2**）：

1. ~~`/kb/search` 未傳 AuthorizationContext；batch delete hard delete~~ → **P0 已修**（C01/C02）
2. ~~Generate／Wiki／Graph／Gateway connector 授權旁路~~ → **P0 已修**（H01–H04）+ ResourcePolicy
3. ~~Outbox 缺 claim／wiki 假 completed／completed 與 outbox 非原子~~ → **P0 已修**（H05–H07）
4. ~~RAGFlow 平行 ingest~~ → **P0 已修**（H09）
5. ~~檢索與 citation 多層~~ → **P1 主幹已收斂**（RetrievalFacade + CitationBuilder）；底層 `kb_retrieval` 仍存在
6. ~~review queue 無生產入佇列~~ → **P0 已接線**（H12）；**仍開**：Graph 無生產寫入、connector 僅 nas_smb 認證、Wiki 無 Web UI
7. ~~安全閘門漏 frontend／npm high／CI `|| true`~~ → **P0 已修**（H08；high=0）
8. ~~prod compose／CD／migration／worker health 假成功~~ → **P0 已修**（H10/H11）；**P2**：`compose/` overlays + digest pins；Mobile → experimental

### 1.2 DD 結論

- **本機功能展示／受控 Pilot**：`Conditional Go`
- **架構可長期演進性**：`Amber → 收斂中`（P0 完成、P1 主幹完成）
- **商業 GA**：`No-Go`（外部滲透 + P2 產品化 + 人工簽核）
- **是否應繼續加功能**：`暫停大功能；優先 P2 產品化與文件真相，再評估新能力`

目前剩餘最大風險已從「授權／一致性 Critical」轉為：**產品表面仍寬於真實支援面**、**部署／評測／Mobile 產品化未完**、以及**外部滲透未做**。

---

## 2. 評估方法與實際證據

本次 DD 不是只讀計畫 checkbox，而是交叉檢查：

- 後端核心：`app/api/`、`app/services/`、`app/gateway/`、`app/tasks/`、`app/models/`
- 前端：`frontend/src/`、routes、API client、production build
- 行動端：`mobile/`
- 部署：三份 `docker-compose*.yml`、Celery、DB init、backup/N-1
- 測試：`tests/`、CI workflow、各類 eval scripts
- 證據：`artifacts/*_last_run.json`
- 計畫：`DEVELOPMENT_PLAN_TRIPLE_INJECTION.md`、`PLAN_PROGRESS.md`、`OPEN_GATES.md`

本次實際執行結果：

- `python -m pytest tests -q` → **260 passed，10 warnings**
- `python -m compileall -q app scripts` → **PASS**
- `frontend/npm ci && npm run build` → **PASS**
- 前端 bundle：約 **1.27 MB minified / 378.71 KB gzip**，Vite 警告 chunk 超過 500 KB
- `npm audit` → **16 vulnerabilities：12 high、2 moderate、2 low**
- Mobile `npm ci` → **失敗：沒有 `package-lock.json`**

注意：測試全綠證明「現有測試所描述的行為沒有回歸」，不代表測試未涵蓋的 ACL／交易競態不存在。

---

## 3. 目標架構原則

Enclave 2.0 應固定以下不變式：

### 3.1 單一權威

- Enclave DB 是唯一 canonical metadata／policy／lifecycle store。
- Enclave pgvector 是預設 primary retrieval index。
- sidecar 只持有可重建 projection，不得成為授權或生命週期權威。

### 3.2 單一授權入口

所有會讀取知識內容的路徑都必須呼叫同一個 Resource PEP：

- Chat
- KB search
- Generate（包含指定 `document_ids`）
- Agent tools
- Wiki list/get/search
- Graph search/traverse
- Connector result
- Reports 再讀取來源

PEP 必須同時處理：

- tenant
- KB membership
- department inheritance
- connector source record allow/deny
- tombstone
- deny-set
- policy revision

### 3.3 單一檢索入口

產品層只依賴一個 `RetrievalFacade`。它內部可以使用：

- canonical `KnowledgeBaseRetriever`
- optional connector/wiki/graph adapters
- 一次 normalize／dedupe／rerank
- 一次 post-authorization
- 一次 citation build

不得由 Chat、Generate、Agent、KB API 各自決定要走 Gateway 或舊 retriever。

### 3.4 單一一致性模型

- 業務寫入與 outbox event 必須同一 transaction。
- worker 必須 claim event（row lock / `SKIP LOCKED` / lease）。
- handler 不得自行 commit 外層 transaction。
- stale `processing` 必須能回收。
- projection 失敗不得標 completed。
- DB constraint 必須支撐 idempotency，而不是只靠「先查再寫」。

---

## 4. 風險分級標準

- **Critical**：可造成未授權大量資料外洩、不可逆資料損壞或整體控制面失效。
- **High**：可造成跨部門／來源資料旁路、事件永久遺失、發布安全判斷失真或主要部署不可用。
- **Medium**：增加維護成本、行為漂移、重複資料、產品誤導或局部可靠性問題。
- **Low**：文件、命名、效能與未來相容性問題。

本次判定 **2 個 Critical、12 個 High**。Critical 為：

- `/kb/search` 授權旁路。
- batch delete 繞過完整 revoke lifecycle。

兩者在受控 Pilot 以外皆屬發布阻斷。

---

## 5. P0：必須先修的高風險

### DD-C01 — `/kb/search` 未傳 AuthorizationContext

**證據**

- `app/api/v1/endpoints/kb.py::search_knowledge_base()`
- 呼叫 `KnowledgeBaseRetriever.search()` 時只傳 `tenant_id/query/top_k`，沒有 `authz`。
- `KnowledgeBaseRetriever` 只有在收到 `authz` 時才套 department 與 connector source-record ACL。

**影響**

任何已登入的同租戶使用者都可能搜尋到其他部門或未被 connector source ACL 授權的文件內容。

**方案**

- 立即建立 `AuthorizationContext.from_user(current_user)` 並傳入。
- 中期移除此獨立查詢入口，統一進 `RetrievalFacade`。
- 新增跨部門、connector no-allow、deny/tombstone API 測試。

**驗收**

- `/kb/search` 與 Chat/Gateway 對相同身份、相同 query 必須得到相同 allow/deny 集合。

---

### DD-C02 — Batch delete 硬刪除，繞過完整 revoke lifecycle

**證據**

- `app/api/v1/endpoints/documents.py::batch_delete_documents()`
- 直接刪 chunks、實體檔與 `Document` row 後 commit。
- 沒有呼叫 `crud_document.tombstone()`。
- 沒有 outbox deleted event、sidecar delete、deny-set、Wiki/Graph tombstone 或 cache invalidation。

**影響**

Enclave DB 已沒有文件，但 RAGFlow／WeKnora／PipesHub projection 仍可能保留並回傳幽靈資料；且 canonical lineage 已被硬刪，難以補償。

**方案**

- 修復前先停用 `/documents/batch`。
- 改成逐筆執行同一個 `DocumentRevocationService`，不要複製單筆 endpoint 流程。
- 大量刪除改為非同步 job，逐筆記錄成功／失敗與重試狀態。

**驗收**

- 批次刪除後 canonical、cache、Gateway、RAGFlow、Wiki、Graph 均不可再讀；失敗項可重試。

---

### DD-H01 — Generate 指定文件繞過部門／來源 ACL

**證據**

- `app/api/v1/endpoints/generate.py`
- `generate_stream()` 對 `req.document_ids` 只檢查：
  - `Document.id`
  - `Document.tenant_id`
- 未檢查 `department_id`、`source_system/source_record_id ACL`、`tombstoned_at`。
- 之後直接讀取 `DocumentChunk.text` 放入生成 prompt。

**影響**

同租戶低權限使用者若取得或猜到其他部門文件 UUID，可要求 Generate 將該文件內容放進 prompt，繞過正常檢索 ACL。

**方案**

- 禁止 endpoint 直接 query 文件內容。
- 新增 `AuthorizedDocumentLoader`，強制使用統一 Resource PEP。
- 針對 department mismatch、connector no-allow、tombstone、deny-set 建 API 測試。

**驗收**

- 低權限使用者指定未授權 `document_id` 必須得到 404/403，且 LLM context 不含內容。

---

### DD-H02 — Wiki 讀取與編譯未套來源文件 ACL

**證據**

- `app/api/v1/endpoints/wiki.py`
- `list_wiki_pages()` / `get_wiki_page()` 僅檢查 tenant + tombstone。
- `compile_wiki()` 允許 employee 提交任意 `kb_id` 與 `source_document_ids`，未驗 KB membership 或來源文件權限。
- Wiki revision 內容可能由受限文件衍生。

**影響**

同租戶使用者可能讀到由其他部門／connector ACL 文件編譯出的摘要，形成「原文件搜不到，但 Wiki 看得到」的衍生資料外洩。

**方案**

- Wiki page 保存可驗證的 source ACL fingerprint／source document set。
- list/get/search 都用同一 Resource PEP 對所有來源求交集或採最嚴格 policy。
- compile 只允許管理角色，並驗 `kb_id` 與每個 source document。

**驗收**

- 任一來源撤權後，Wiki 在 projection 收斂前也必須立即 deny。
- 建立跨部門與 connector source ACL 的 API E2E。

---

### DD-H03 — Gateway connector 後濾不是 object-level ACL

**證據**

- `app/gateway/router.py`
- connector hit 後呼叫 `GatewayAuthorizer._check_source_acl(authz, [src])`。
- `app/gateway/authorization.py::_check_source_acl()` 沒有使用 `source_systems` 內容，也沒有接收／比對 hit 的 `source_record_id`。
- 目前邏輯本質上是「使用者有任何 mapped principal，且沒有任一 deny row」即允許。
- 相較之下，`KnowledgeBaseRetriever._apply_source_acl_filter()` 會對 `Document.source_record_id` 檢查 allow/deny。

**影響**

PipesHub 直接回傳的 connector 結果可能因使用者擁有其他資源的 principal mapping 而被錯誤放行。

**方案**

- 建立公開 `authorize_source_record(authz, source_system, source_record_id)`。
- 禁止 Router 呼叫 private `_check_source_acl`。
- Adapter contract 強制每個 connector hit 帶 `source_system` + `source_record_id`。
- 缺欄位時 fail closed。

**驗收**

- A record allow 不得授權 B record。
- allow + deny 同時存在時 deny 優先。

---

### DD-H04 — Graph ACL 未套 connector source-record ACL

**證據**

- `app/services/graph_service.py::_entity_allowed()`
- Graph entity 有來源文件時只檢查：
  - deny-set
  - tenant/department（`authz.can_access_document`）
- 沒有對 connector 文件執行 `SourceAclEntry` object-level 檢查。

**影響**

同部門但沒有來源系統權限的使用者，可能透過 Graph 看到 connector 文件衍生實體。

**方案**

- Graph、Wiki、document、connector 共用同一 `ResourcePolicyService`。
- 不得在各 service 複製「部分 PEP」。

---

### DD-H05 — Outbox event 沒有可靠 claim，可能重複處理或永久卡住

**證據**

- `app/tasks/outbox_worker.py::process_outbox_batch()`
- 以一般 query 取 `pending/failed`，沒有 row lock、`FOR UPDATE SKIP LOCKED` 或 lease。
- `_dispatch_event()` 將狀態設為 `processing` 後只 `flush`。
- poller 不會重新撿 `processing`。
- 多 worker／task overlap 可能同時讀到相同事件。

**額外風險**

- `_handle_connector_event()` 呼叫 `run_sync()`，後者多次 `db.commit()`。
- `_handle_kb_event()` → `WikiCompiler.compile_kb()` 也會 commit。
- handler 內 commit 會把外層 event 的 `processing` 一併提交；若後續 crash，事件永久停在 processing。

**方案**

- 每次 claim 使用 `SELECT ... FOR UPDATE SKIP LOCKED`。
- 加入 `claimed_at`、`claimed_by`、`lease_until`。
- worker 啟動／排程回收逾時 processing。
- handler 不得 commit；改為 transaction boundary 由 worker 控制。
- side-effect 使用 provider idempotency key。

**驗收**

- 兩個 worker 同時跑，單一 event 只能被 claim 一次。
- handler 在 provider call 前／後 crash，event 可恢復且不重複產生 artifact。

---

### DD-H06 — Wiki outbox 失敗會被吞掉並標 completed

**證據**

- `app/tasks/outbox_worker.py::_handle_wiki_event()`
- WeKnora compile exception 只 `logger.warning`，最後無條件 `event.status = "completed"`。

**影響**

下游 Wiki projection 失敗後不會 retry／DLQ，控制面誤認事件完成。

**方案**

- Wiki handler 必須沿用 document projection 的 failure semantics。
- 失敗 raise → retry → DLQ；成功才 completed。
- ProjectionStatus 必須記錄 wiki provider 狀態。

---

### DD-H07 — 文件完成後，outbox publish 失敗仍回報成功

**證據**

- `app/tasks/document_tasks.py`
- 文件先更新為 completed。
- `document_processed` publish/commit 外包在 `try/except`。
- 失敗時 rollback + log，但 task 仍繼續回傳 completed。

**影響**

canonical 文件可搜尋，但 RAGFlow／WeKnora projection 永遠缺失；沒有補償事件。

**方案**

- 文件狀態更新與 outbox event 同一 transaction。
- 若 outbox 無法寫入，task 必須 retry 或狀態進入 `projection_pending/error`，不能靜默成功。

---

### DD-H08 — 安全閘門漏掃 frontend，現有 PASS 是假安全綠燈

**證據**

- `scripts/security_findings_gate.py` 只跑 pip-audit、Bandit、3 個 API smoke。
- 沒有 npm audit、container scan、secret scan。
- `artifacts/security_scan_last_run.json` 宣稱 `PASS/open_critical_high=0`。
- 本次實跑 frontend `npm audit`：**12 high**。
- `.github/workflows/ci.yml` 對 pip/npm audit 使用 `|| true`，所以漏洞不會阻擋 CI。

**影響**

計畫可在已知 high dependency finding 存在時仍宣稱「無未處理 Critical/High」。

**方案**

- security gate 納入 frontend `npm audit --audit-level=high`。
- 只計 production dependencies與完整 dev-tool 風險分開呈現。
- CI 移除 `|| true`，或要求有時限的 signed exception。
- 加入 Trivy/Grype（image）、Gitleaks（secret）、SBOM digest。

**驗收**

- 任何未豁免 high/critical 都使 security gate 非 0。
- `FINDINGS_REGISTER` 不得由不完整掃描覆寫成「0 findings」。

---

### DD-H09 — RAGFlow 存在平行 ingest 與 pending 重送

**證據**

- `app/services/parse_pipeline.py::_parse_via_ragflow()` 直接呼叫 `RAGFlowHTTPAdapter.ingest()`。
- `crud_document.create()` 另建立 `created` outbox event。
- `process_document_task` 完成後再建立 `document_processed` event。
- `app/tasks/outbox_worker.py::_dispatch_to_provider()` 對 `created/updated/document_processed` 都呼叫 adapter ingest。
- projection 只有 `converged` 才跳過；`submitted/pending` 在事件重試時可能再次 ingest。

**影響**

單一文件可能在 RAGFlow 建立多份 provider document；`created` payload 尚無完整 `file_path/content_uri` 又會先失敗重試，擴大重複與映射漂移。

**方案**

- 規定 RAGFlow 角色二選一：parse service 或 projection service，不得兩條路都寫。
- 最小修復：只有 `document_processed` 可觸發 sidecar ingest；`created` 不投影內容。
- pending 必須 reconcile provider resource，不可重新 POST。

---

### DD-H10 — 生產 Compose 與 CD pipeline 不相容

**證據**

- `docker-compose.prod.yml` 的 web/worker/frontend 使用 `build:`，沒有對應 GHCR `image:`。
- staging CD 執行 `docker compose ... pull`；production CD 雖先 `docker pull/tag`，compose 仍可能現場 build。
- CD health 打 `http://localhost:8000/health`，prod web 只有 `expose: 8000`，對主機沒有 publish。

**影響**

部署可能沒有使用剛產生的版本化 image；health 可能永遠失敗，或碰巧打到主機其他服務而假通過。

**方案**

- prod compose 使用明確 `${IMAGE_PREFIX}/backend:${IMAGE_TAG}` 與 frontend image。
- health 經 edge `http://localhost/health`，或 `docker compose exec web`。
- 新增 CI `docker compose -f docker-compose.prod.yml config` + 完整 stack smoke。

---

### DD-H11 — Migration 與 worker health 允許假成功

**證據**

- production deploy：`alembic upgrade head || true`。
- worker healthcheck：`grep -q OK || exit 0`。
- N-1 artifact 目前是 dry-run，不是實際 downgrade/upgrade。

**影響**

Schema migration 失敗仍宣告部署成功；Celery 已死仍被 Docker 判健康；outbox 因此永久不收斂。

**方案**

- migration fail 必須停止部署並觸發 rollback。
- worker health 失敗回非 0。
- staging 定期實跑 N-1 與 outbox convergence。

---

### DD-H12 — Review queue 是已曝光但未接線的產品功能

**證據**

- Web/Mobile 有 review UI 與 `/agent/review/*` API。
- `ReviewQueueManager.enqueue()` 在 production code 沒有任何呼叫者。
- `DocumentClassifier` 沒有接入 watcher/scan。
- Mobile 傳 `queue_for_review=true`，documents upload endpoint 沒有此參數。

**影響**

使用者看到完整功能入口，但 queue 永遠無法由正常流程產生資料；這是產品可信度與維護成本問題。

**方案**

- 二選一，不保留半套：
  1. watcher → classifier → enqueue → approve → ingest 完整閉環。
  2. 下架 Web/Mobile review UI，將 direct ingest 說清楚。

---

## 6. P1：架構收斂風險

### DD-M01 — 三層檢索與兩次 citation build

**現況**

- `KnowledgeBaseRetriever`：canonical semantic/BM25/RRF + SQL ACL。
- `GatewayRouter + ResultAggregator`：fan-out、聚合、後授權、CitationBuilder。
- `UnifiedRetriever`：再次 normalize、dedupe、post-authorize、再次 build citation。

`UnifiedRetriever` 呼叫 Router 時沒有傳 DB；Router citation 缺 DB enrichment。之後 UnifiedRetriever 又丟棄 Router citations，自建 citation 並把 `document_revision` 固定為 1。

**影響**

- score 語意被多次正規化。
- citation 在 `/gateway/search` 與 Chat 可能不同。
- lineage、版本、source record、page/bbox 在不同入口不一致。

**收斂方案**

- `KnowledgeBaseRetriever` 僅做 canonical candidate retrieval。
- `GatewayRouter` 改名／收斂為唯一 `RetrievalFacade`。
- normalize/dedupe/rerank/citation 各只做一次。
- Chat、Generate、Agent、KB API 只呼叫 Facade。

---

### DD-M02 — Chat 的 fallback 會靜默降級

**證據**

- `app/services/chat_orchestrator.py::retrieve_context()`
- Gateway 失敗後直接 fallback 到 `KnowledgeBaseRetriever`，最後回 status success。

**好處**

- canonical index 可用時，sidecar 故障不拖垮聊天。

**問題**

- connector/wiki/graph 結果消失但使用者看不到降級狀態。
- Gateway audit／citation 路徑中斷。

**方案**

- 保留 fallback，但回傳 `degraded=true`、providers omitted、correlation id。
- fallback 也必須經相同 PEP/citation builder。

---

### DD-M03 — Citation revision 的「穩定 hash」其實不穩定

**證據**

- `app/gateway/citation.py::_coerce_revision()`
- 對 opaque external version 使用 Python `hash(str(value))`。
- Python hash 預設跨 process 隨機化，重啟後結果不同。
- `completeness([])` 回傳 rate 1.0，具有 vacuous-pass 風險。

**方案**

- opaque version 以 SHA-256 截斷轉 int，或直接保存 string revision。
- 空 citation sample 應回 `not_evaluated`，不能是 100%。

---

### DD-M04 — DB constraint 不足以支撐併發 idempotency

**證據**

- `Document` 沒有 `(tenant_id, source_system, source_record_id)` 唯一限制。
- `DocumentChunk` 沒有 `(document_id, chunk_index)` 或 `(document_id, chunk_hash)` 唯一限制。
- `ProjectionStatus` 沒有 `(resource_type, resource_id, provider, provider_instance_id)` 唯一限制。
- `GatewayResource` unique 包含 nullable `provider_instance_id`；PostgreSQL 預設允許多個 NULL，仍可能重複。
- 多處採「先 query 再 insert」，併發下不是原子操作。

**方案**

- 加 partial unique indexes／`NULLS NOT DISTINCT`（依 PostgreSQL 版本）。
- 使用 database upsert。
- migration 前先做 duplicate report 與 repair。

---

### DD-M05 — Adapter 三代並存（部分已清：2026-08-01）

**已處理**

- 刪除重複 `app/gateway/adapters.py`。
- `adapters/__init__.py` 僅匯出 HTTP／Enclave；stub 不進 production export。

**仍存（可接受／測試用）**

- `app/gateway/adapters/base.py`：Base/Mock（測試）。
- `app/gateway/adapters/{ragflow,pipeshub,weknora}.py`：fail-closed stub（測試契約）。
- `*_http.py`：真正 production adapter。
- `adapters/__init__.py` export 的名稱仍以 stub 為主。

**影響**

誤 import、測試通過但掛錯實作、維護者無法立即辨識 production path。

**方案**

- production interface 只留 `adapters/base.py` + `*_http.py`。
- mock 移到 `tests/fakes/`。
- stub 改名 `Disabled*Adapter` 或刪除。
- 移除同名 `app/gateway/adapters.py`。

---

### DD-M06 — Connector 支援面過度宣稱

**證據**

- `connector_manager.GA_CONNECTORS` 列出 NAS、SharePoint、Drive、Confluence、Jira、S3、GitHub、Slack。
- `CONNECTOR_SCHEMAS` 只有 NAS、SharePoint、Drive。
- `validate_connector_config()` 對未知類型直接放行。
- 真正 certified 只有 `nas_smb`。

**方案**

- 分成 `CERTIFIED_CONNECTORS`、`EXPERIMENTAL_CONNECTORS`、`PLANNED_CONNECTORS`。
- API create 只接受 certified/explicitly experimental。
- 前端不得把 planned 類型顯示成可用。

---

### DD-M07 — Agent 有兩套不相連的產品故事（決策：2026-08-01）

**產品決策（P1）**

| 路線 | 決策 | 說明 |
|------|------|------|
| FolderWatcher → Classifier → ReviewQueue → ingest | **Keep / 正式產品面** | `REVIEW_QUEUE_ENABLED=true`（預設）；核准後 `skip_review` 入庫 |
| ReAct / MCP / Sandbox / tool-approval Agent | **Experimental** | 保留 API／測試契約；不作為本機 Pilot 預設入口；README 標 experimental |

原問題陳述：

**證據**

- 已有產品入口：`file_watcher`、`classifier`、`review_queue`、`/agent/*`、Web UI。
- 另一套：`react_loop.py` 自有 ToolRegistry。
- 又一個 `app/agent/tool_registry.py` 自有 ToolRegistry。
- `AgentSandbox`、`mcp_tools.py` 主要是契約／測試，未形成清楚的產品入口。
- `/agent-approvals` 與既有 `/agent/review` 是不同審批概念。

**方案**

- 產品短期只保留「Ingestion Agent」。
- ReAct/Tool Agent 標為 experimental pack，合併兩個 registry 後才能啟用。
- approval request 與 review queue 明確分工或合併。

---

### DD-M08 — Wiki/Graph 是後端能力，不是完整產品

**現況決策（2026-08-01 P2）**：採「誠實 API-only」而非假完整 UI。

- 前端導航：**知識編譯（API-only）** 說明頁（`/knowledge-compiler`）
- API：`GET /wiki/product-status`、`GET /graph/product-status` + 回應 header `X-Enclave-Product-Status`
- Graph 明確標 **無生產寫入路徑**（DD-M09A）

**證據（歷史）**

- 後端有 `/wiki`、`/graph`。
- Web routes 沒有 Wiki、Graph、Gateway、Agent Approvals。

**方案**

- 二選一：
  1. 補最小 UI：page list/detail、compile status、source citations、graph inspect。
  2. 明確定位為 API-only/experimental，不計入「完整產品功能」。

---

### DD-M09 — SSO 是未掛載 skeleton

**證據**

- `endpoints/sso.py` 有 route helper 與 token exchange。
- `app/api/v1/api.py` 未 include SSO router。
- 檔案說明仍稱 skeleton。

**方案**

- 本機版本若不做 SSO：移到 `experimental/`，不要列產品能力。
- 要做：補 route、tenant config、callback E2E、UI。

---

### DD-M09A — Graph API 沒有生產寫入路徑

**證據**

- `GraphService.upsert_entity()` 只被 tests 與 `eval_wiki_graph_quality.py` 呼叫。
- WeKnora/outbox 沒有把實體寫入 `GraphEntity` 的 production projection。
- Web 亦沒有 Graph UI。

**影響**

Graph API 與測試可以通，但正式資料庫預期為空；不應列為完成的產品閉環。

**方案**

- 未補 projection 前將 Graph 標為 experimental/hidden。
- 若保留，建立 WeKnora → canonical GraphEntity 的可重建 projection，並套統一 PEP。

---

### DD-M09B — URL ingest 與 watcher reindex 的 projection 語意不一致

**證據**

- `process_url_task()` 寫入 canonical chunks 後沒有發 `document_processed` outbox。
- watcher reindex 直接刪舊 chunks 再重跑，沒有先建立 versioned update event。

**影響**

不同 ingest 入口在 sidecar、revision 與 revoke 行為上不一致。

**方案**

- 所有來源統一產生同一個 `DocumentReady` domain event。
- reindex 使用 revision，不在可搜尋版本上原地清空 chunks。

---

## 7. P1：部署、供應鏈與運維

### DD-M10 — 三份 Compose 沒有單一可組合真相

**現況（2026-08-01 P2）**

- `compose/sidecars.yml` + `compose/enterprise.yml` 為 overlay 真相；`docker-compose.profiles.yml` 以 `include` 組合。
- `compose/pack-enabled.env` 強制 standard／enterprise 時 pack flag 與 sidecar 同開。
- `compose/image-pins.env`：PipesHub／WeKnora 釘 tag@digest；其餘釘 immutable tag（禁 `latest`）。
- Prod 核心仍 `docker-compose.prod.yml`；開 pack 時必須 `-f compose/sidecars.yml --profile standard`（見 `compose/README.md`）。

**風險（殘餘）**

- 現場若只開 `RAGFLOW_ENABLED=true` 卻未掛 sidecar overlay，DNS 仍會失敗（需 runbook／preflight）。

**方案**

- 一個 base compose + overlays：`compose.yml`、`compose.sidecars.yml`、`compose.prod.yml`。
- Profile 同時控制 service 與 module env，禁止兩套開關漂移。
- preflight 必須檢查「service running + adapter registered + health + credentials」。

---

### DD-M11 — Sidecar image 大量使用 `latest`

**現況（2026-08-01 P2）**

- `compose/image-pins.env` + `compose/sidecars.yml` 已釘 immutable tag；PipesHub `0.4.5`、WeKnora `v0.7.1` 含 `@sha256` digest。
- Ollama／MinIO／Langfuse／Neo4j／Mongo 釘版本 tag（禁 `latest` 預設）。
- 殘餘：RAGFlow 等可再補 digest；SBOM 應記錄實際 pull digest。

---

### DD-M12 — Frontend high vulnerabilities 未關閉

本次 audit 顯示 direct 或 transitive high 包含：

- `axios`
- `react-router-dom` / `react-router`
- `vite`
- `rollup`
- `postcss`
- `minimatch`、`picomatch`、`brace-expansion` 等

部分屬 dev server/tooling，部分 direct runtime dependency；不能全部視為可忽略。

**方案**

- 先執行 lockfile 升級分支與 regression build/E2E。
- 分 production/runtime 與 dev-only 風險。
- 無法立即修的建立 exception：owner、影響、補償控制、到期日。

---

### DD-M13 — Mobile 不可重現建置

**現況（2026-08-01 P2）**

- 採「非主產品」路徑：`mobile/EXPERIMENTAL.md` 標明不屬 GA 核心；Web `frontend/` 為準。
- 若日後納入 2.0：再補 lockfile、Expo doctor、TypeScript、Android build CI。

---

### DD-M14 — Backup/restore 與 credential storage 不一致

**現況（2026-08-01 P2）**

- OAuth token 預設改存 `var/credentials/`（`CONNECTOR_CREDENTIAL_DIR` 可覆寫）；**禁止**落在 `uploads/` 下。
- `uploads/` 備份不再預設夾帶 connector secret（仍需確認 `backup.sh`／`ops_lifecycle` 未掃到 `var/credentials` 除非明確加選項）。
- 殘餘：仍為本地明文 JSON；正式環境應改 vault/KMS／envelope encryption；統一 DB+uploads 備份入口；restore 加 path traversal 驗證。

---

### DD-M15 — Mobile push 與 review mode 為半套

**證據**

- Mobile 可登記 push token，但後端沒有 Expo push sender。
- review upload query parameter 沒有後端對應。

**方案**

- 在完成 sender/queue 前，UI 與 README 標 Beta 或移除入口。

---

### DD-L01 — Web bundle 過大

Production build 成功，但主 JS 約 1.27 MB minified。應對 charts、reports、admin pages 使用 route-level lazy loading。

---

## 8. 測試與閘門可信度

### 8.1 已有優點

- 260 個 backend tests 全過。
- 有 DB/Redis CI service。
- 有 adapter contract、Gateway、ACL、outbox、pilot、revoke、module disable。
- frontend production build 可完成。
- Pilot artifact 確實使用 `ragflow/deepdoc`。

### 8.2 主要盲點

- Generate `document_ids` 沒有跨部門／source ACL 測試。
- `/kb/search` 沒有驗證 AuthorizationContext 必傳的 API 測試。
- batch delete 沒有 projection revoke E2E。
- Wiki API 沒有 source-derived ACL E2E。
- Graph 沒有 connector source ACL E2E。
- Gateway connector 測試沒有「同一 principal 只允許特定 record」。
- RAGFlow 沒有驗證單一 logical document 只建立單一 provider resource。
- Outbox 沒有雙 worker claim／crash recovery 測試。
- Review queue 測試沒有從真正 watcher/upload 入口產生 ReviewItem。
- CI 的 Playwright 只 serve static dist，沒有啟動 backend；能證明的整合深度有限。
- Prod compose/CD 沒有實際啟動與 health smoke。
- Security audit 不阻擋 CI。
- `plan_progress_gate` 預設不跑 pytest；`--strict` 只代表「沒有已勾且 evidence=false」，不是品質總評。
- parse golden 只有 native txt/csv baseline，不是 page/table/OCR DeepDoc 黃金集。
- Wiki eval 主要證明 schema/revoke + WeKnora health，不是生產語料品質。
- retrieval gate Hit@5 = 0.67，只略高於 0.6，不能稱市場級品質。

### 8.3 建議新增的架構守門測試

- `test_all_knowledge_reads_use_resource_pep`
- `test_kb_search_requires_authorization_context`
- `test_batch_delete_uses_revocation_service`
- `test_generate_explicit_document_department_denied`
- `test_generate_explicit_connector_record_denied`
- `test_wiki_source_acl_intersection`
- `test_graph_connector_source_acl`
- `test_gateway_connector_acl_per_record`
- `test_outbox_two_workers_single_claim`
- `test_outbox_stale_processing_recovered`
- `test_wiki_projection_failure_retries`
- `test_citation_revision_stable_across_process`
- `test_ragflow_single_logical_ingest`
- `test_review_queue_has_production_producer`
- `test_prod_compose_uses_built_image_and_health`
- `test_no_production_imports_from_stub_adapters`
- `test_certified_connector_surface_matches_api`

---

## 9. 建議的目標模組邊界

### 9.1 保留

- `Identity & Policy`
- `Canonical Knowledge Store`
- `Ingestion Pipeline`
- `RetrievalFacade`
- `Outbox/Projection`
- `Audit/Operations`
- Sidecar adapters（只留 HTTP production implementation）

### 9.2 合併

- `GatewayRouter` + `UnifiedRetriever` + citation orchestration → `RetrievalFacade`
- 兩套 ToolRegistry → 一套
- `/agent/review` 與 `/agent-approvals` 的狀態模型／產品語意
- 三套 compose → base + overlays

### 9.3 降級為 experimental

- SharePoint/Google OAuth（依使用者決策，本機階段 SKIP）
- 未認證 connector types
- ReAct/MCP/Sandbox Agent
- Wiki/Graph（直到 ACL + UI 閉環）
- SSO
- Mobile（直到可重現 CI）

### 9.4 移除／搬家

- `app/gateway/adapters.py`
- production package export 的 disabled stub adapters
- 測試 mock 移到 `tests/fakes`
- 過時的架構文件內容

---

## 10. 收斂路線圖

### 0–14 天：P0 Correctness Freeze

期間不新增功能。

1. 先停用／修正 DD-C01 `/kb/search` 與 DD-C02 batch delete。
2. 修 DD-H01～H04 授權旁路。
3. 修 DD-H05～H07 outbox transaction/claim/retry。
4. 消除 DD-H09 RAGFlow 平行 ingest。
5. 修正 prod compose/CD、migration 與 worker health。
6. Security gate 納入 npm，處理 12 high。
7. Review queue 做接線或下架決策。
8. 加對應回歸測試並更新計畫／README 的安全狀態。

**出口**

- P0 tests 全過。
- 無未處理 Critical／授權 High。
- outbox crash/recovery 測試通過。
- security gate 不再漏 frontend。
- prod compose 使用指定 image，migration/health 失敗會阻擋部署。

### 10.1 P0 實作狀態（2026-08-01）

| ID | 狀態 | 實作摘要 |
|----|------|----------|
| DD-C01 | **已修** | `/kb/search` 傳入 `AuthorizationContext`；KB deny-set 後濾 |
| DD-C02 | **已修** | 單筆／批次刪除走 `DocumentRevocationService`（tombstone+deny+wiki/graph） |
| DD-H01 | **已修** | Generate `document_ids` 經 `ResourcePolicyService.load_authorized_document_text` |
| DD-H02 | **已修** | Wiki 來源文件交集 ACL；compile 需 admin |
| DD-H03 | **已修** | Gateway connector 後濾改 object-level `source_record_id` |
| DD-H04 | **已修** | Graph entity ACL 走 ResourcePolicy（含 connector） |
| DD-H05 | **已修** | Outbox `FOR UPDATE SKIP LOCKED` claim + stale processing 回收 |
| DD-H06 | **已修** | Wiki compiled 失敗 raise／retry，不再吞錯標 completed |
| DD-H07 | **已修** | `document_processed` 與 status=completed 同交易；URL 任務同樣補齊 |
| DD-H08 | **已修** | CI／audit 納入 frontend；`npm audit` 高危清至 0（axios 等升級 + `react-router` override 8.3.0） |
| DD-H09 | **已修** | `created` 不投影內容；pending／parse 已 ingest → reconcile；禁止重複 POST |
| DD-H10 | **已修** | prod compose 明確 `image:`；CD `--no-build`；health 經 edge／compose exec |
| DD-H11 | **已修** | migration 移除 `\|\| true`；worker health 失敗回非 0 |
| DD-H12 | **已修** | watcher → classifier → enqueue；核准 `skip_review=True` 入庫（`REVIEW_QUEUE_ENABLED`） |

驗證：`pytest tests` → **277 passed**（含 `tests/test_dd_p0_correctness_freeze.py`、`tests/test_retrieval_facade_architecture.py`）。  
frontend production build：PASS；`npm audit --audit-level=high`：0。

P0 出口條件已達成。P1 主幹已完成（見 §10.2）。下一階段為 **P2 Productization**。

### 10.2 P1 實作狀態（主幹完成）

| 項目 | 狀態 | 摘要 |
|------|------|------|
| ResourcePolicyService | **已有** | P0 已建立並接入 Generate／Wiki／Graph／Gateway |
| RetrievalFacade | **已接線** | `app/services/retrieval_facade.py`；KB／Chat／Generate／Agent kb_search |
| 統一 CitationBuilder | **已接線** | UnifiedRetriever／Facade 皆走 `gateway.citation.CitationBuilder` |
| 架構守門測試 | **已加** | `tests/test_retrieval_facade_architecture.py` |
| production stub export | **已清** | `adapters/__init__` 只匯出 HTTP／Enclave；刪除重複 `adapters.py` |
| DB unique constraints | **已加** | migration `p1_dd_m04_unique_indexes_001` + `scripts/duplicate_constraint_report.py` |
| Agent keep/experimental | **已決策** | **Keep**：FolderWatcher + ReviewQueue（已接線）。**Experimental**：ReAct/MCP/Sandbox（不進預設產品導航） |

P1 出口（知識讀取經 Facade／PEP、citation 單一 builder、production 不含 stub export）已達成。其餘產品化項見 P2。

### 15–45 天：P1 Architecture Convergence

1. 建立單一 `ResourcePolicyService`。
2. 建立單一 `RetrievalFacade`。
3. 移除重複 aggregator/citation path。
4. 加 DB unique constraints + duplicate migration report。
5. 清理 adapter 三代與 connector 宣稱。
6. Agent 產品線做 keep/experimental 決策。

**出口**

- 所有知識讀取 path 由 architecture test 證明經同一 PEP。
- 所有 citation 由同一 builder 產生。
- production import graph 不含 stub。

### 46–90 天：P2 Productization

1. ~~統一 Compose overlays~~（`compose/` + profiles `include`）；preflight 仍待加強。
2. ~~Pin sidecar image digest~~（PipesHub／WeKnora digest；其餘 immutable tag）。
3. ~~Wiki/Graph 正式降級 API-only~~（誠實產品面）。
4. ~~Mobile 移出主發布~~（`mobile/EXPERIMENTAL.md`）。
5. 補真實 DeepDoc 黃金集、Wiki 生產語料、較大型 retrieval benchmark。
6. 外部滲透與發版演練；憑證移出 uploads；更深 ACL／outbox 雙 worker 測試。

---

## 11. 架構決策建議

### 建議採用：「收斂式 2.0」，不是重寫

不建議全面重寫。理由：

- canonical DB、Document/Chunk、KB retrieval、Celery、NAS、RAGFlow Pilot 已有可用資產。
- 主要問題是責任重複與 path bypass，可用 strangler/refactor 解決。
- 全面重寫會重新引入 ACL、migration、idempotency 風險。

建議順序：

1. 先建立 Facade/Policy 的新唯一介面。
2. 逐一把 Chat、Generate、Agent、Wiki、Graph 遷入。
3. 用 architecture tests 防止新旁路。
4. 最後刪舊路。

---

## 12. 發布判定與不得宣稱事項

P0 已於 2026-08-01 關閉後仍不應宣稱：

- 「Enclave 2.0 已全面 production-ready／商業 GA」
- 「所有 GA connectors 已認證」（僅 nas_smb）
- 「外部滲透已完成」
- 「Wiki/Graph 已有完整 Web UI」

可以誠實宣稱：

- 本機 canonical KB、NAS ingest、RAGFlow parse、search/revoke Pilot 已完成。
- sidecar 可關閉且核心仍可運作。
- 2.0 Control Plane 架構方向成立。
- **P0 Correctness Freeze 已完成**（授權 Critical/High、outbox claim、RAGFlow 單一路徑、部署／安全閘門、review 接線）。
- **P1 主幹完成**：`RetrievalFacade` + 統一 `CitationBuilder` 已接入 KB／Chat／Generate／Agent；架構測試見 `tests/test_retrieval_facade_architecture.py`。
- **下一優先**：外部滲透／法律／DR（人工閘門）；可選 DeepDoc／retrieval benchmark。

---

## 13. DD 風險總結

### Critical（發布阻斷）

- `/kb/search` 未傳 authz
- batch delete 繞過 revoke lifecycle

### High（立即）

- Generate explicit document ACL bypass
- Wiki derived-content ACL gap
- Connector Gateway 非 object-level ACL
- Graph connector source ACL gap
- Outbox 無 claim／stale recovery + handler commit
- Wiki outbox failure 假 completed
- document_processed publish failure 靜默成功
- RAGFlow 平行 ingest／pending 重送
- Security gate 漏 frontend high vulnerabilities
- Prod compose/CD image 與 health 不一致
- Migration/worker health 假成功
- Review queue 無 production producer

### Medium（下一階段）

- 三層 retrieval／兩套 citation
- Chat fallback 無降級訊號
- citation revision 非 deterministic
- DB unique constraints 不足
- adapter 三代
- connector 支援面過度宣稱
- Agent 雙產品線
- Wiki/Graph 無 UI
- SSO skeleton
- Graph 無 production write projection
- URL/watcher ingest projection 語意不一致
- Compose 三套真相
- latest image tags
- Backup、uploads 與 credentials 分裂
- Mobile 無 lockfile／CI
- Mobile push/review mode 半套

### Low

- Web bundle 過大
- Pydantic v2 deprecated config warnings
- 過時的 `SYSTEM_ARCHITECTURE.md`
- OAuth2 OpenAPI tokenUrl 與實際 auth prefix 需校正

---

## 14. 最後結論

Enclave 2.0 已有可保留的產品核心，不需要推倒重來；但目前仍處於「功能完成、架構尚未完全收斂」的階段。

真正能避免它變成拼裝車的做法不是再加更多功能，而是執行四個收斂：

1. **所有知識讀取只走一個 Policy/PEP。**
2. **所有搜尋只走一個 RetrievalFacade。**
3. **所有跨服務寫入只走一個可靠 Outbox transaction model。**
4. **產品宣稱只反映 certified、UI 可達、測試涵蓋的能力。**

完成 P0 + P1 後，Enclave 2.0 才能從「能跑的整合產品」提升為「可長期維護的產品架構」。
