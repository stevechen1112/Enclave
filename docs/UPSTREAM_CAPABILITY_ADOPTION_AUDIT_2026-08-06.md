# Enclave × github_projects 特定能力深度稽核與採用決策

**文件版本**：1.0  
**稽核日期**：2026-08-06  
**稽核範圍**：Enclave 與六項候選能力來源  
**文件性質**：原始碼證據稽核、採用／不採用決策與後續驗收規格  
**關聯產品文件**：`docs/MANUFACTURING_KNOWLEDGE_ASSISTANT_PRODUCT_VISION.md`

---

## 1. 稽核目的

先前依 Enclave 的能力現況與「製造業知識作業平台」定位，提出六個可能補強方向：

1. OpenDocuments 的檢索策略
2. OpenAI Knowledge Retrieval 的評測框架
3. WeKnora 的語音、IM、ReAct、MCP 與 HITL
4. OpenKB 的長文知識編譯與 Skill Factory
5. OpenRAG 的工作流、Docling 與 MCP
6. PipesHub 的企業連接器

本次不是再次閱讀 README，而是逐項核對：

- 上游專案是否真的有該能力
- 能力是否已接進上游正式路徑
- Enclave 是否已有等價或更強能力
- 是否與 Enclave ADR／主索引／權限模型衝突
- 應採原生實作、adapter／sidecar、模式借鑑，或明確不採用
- 要用什麼測試證明有增量，而不是「接線即完成」

---

## 2. 結論先行

前述六點方向大致正確，但深查後必須修正為：

> **不是六項全部植入，而是三項立即補強、兩項條件式採用、一項需求驅動。**

### 2.1 建議立即補強

1. **OpenDocuments 檢索模式**
   - 優先：Parent Document、Sibling Expansion、Context Fitting
   - 次優先：Embedding Cache、feature-flagged Multi-query
   - 不建議恢復：HyDE 預設路徑

2. **Enclave 評測單一設定與錯誤分層**
   - 借 OpenAI KR 的 YAML／報告 DX
   - 不採其同 corpus synthetic eval 作泛化證明
   - Enclave 的 Blind Z hold-out、ACL gate、McNemar 消融必須保留

3. **WeKnora Agent 執行面的設計模式**
   - 借：ASR 入庫、IM adapter、MCP Client、MCP HITL、ReAct engine
   - Enclave 自建：voice-first Interaction Gateway、Fixed Form、職能模組、正式簽核
   - 不以 WeKnora RBAC／UI 取代 Enclave

### 2.2 條件式採用

4. **OpenKB**
   - 借：長文 PageIndex、編譯／semantic lint、Skill eval 思路
   - 不整包導入
   - 老師傅 know-how 應在 Enclave 原生建立知識卡與治理

5. **OpenRAG**
   - 不引入 Langflow 作主 runtime
   - 可獨立評估 Docling Serve 與 read-only FastMCP
   - Enclave QueryPlan／MultiStep 已是產品主路徑，不需替換

### 2.3 需求驅動

6. **PipesHub**
   - 保持 sidecar
   - 每個連接器逐一認證
   - 不宣稱 30+／40+ 連接器已是 Enclave GA
   - SharePoint／Drive／ERP 只在有客戶需求與真實 OAuth 時施工

---

## 3. 稽核方法與誠信原則

### 3.1 證據優先序

本文件採以下證據層級：

1. 上游與 Enclave production call site
2. 契約測試、live artifact 與真實 sidecar
3. feature flag 後的實作
4. PoC／stub
5. 文件宣稱或 README

若 README 與程式不一致，以實際 call site 為準。

### 3.2 「已具備」的判準

要宣稱 Enclave 已具備某能力，至少需要：

- 主路徑或明確可啟用路徑
- 真實 API／資料面，不是固定回傳的 stub
- 權限與 tenant context
- 錯誤處理與 fail-closed
- 測試或 live artifact
- 對產品預設開關有清楚記錄

### 3.3 「值得採用」的判準

不是上游有功能就採用。候選能力必須：

- 解決已觀測到的 Enclave failure mode
- 不破壞 canonical index、PEP、FusionPolicy 與 source verifier
- 可 feature flag／回滾
- 有增量評測與延遲／成本預算
- 新 hold-out 可證明泛化

---

## 4. OpenDocuments：檢索策略深查

### 4.1 上游確實存在的能力

#### Multi-query

證據：

- `github_projects/OpenDocuments/packages/core/src/rag/multi-query.ts`
- `expandMultiQuery()` 以 LLM 產生多個同義查詢
- 保留原 query、去重，失敗回退原 query
- 預期各 query 並行檢索後用 RRF 合併

OpenDocuments 的 profile：

- fast：關閉
- balanced：3 個變體
- precise：5 個變體

#### Parent Document

證據：

- `github_projects/OpenDocuments/packages/core/src/rag/parent-doc.ts`
- `attachParentContext()` 將 chunk 替換為較長的 `parentSection`
- 相同文件、相同 parent 會去重

#### Sibling Expansion

證據：

- `packages/core/src/rag/retriever.ts`
- 取相鄰 chunk 並降低 score

#### Context Fitting

證據：

- `packages/core/src/rag/context-window.ts`
- 依 token budget 保留高價值內容，避免 parent／sibling 擴展後超窗

#### Hybrid／RRF

OpenDocuments 使用 dense＋FTS5，再做 RRF；Enclave 已有 pgvector＋BM25＋RRF，概念高度重複。

#### Rerank

OpenDocuments 有 heuristic 與逐 candidate 的 LLM cross-encoder；Enclave 已有 Voyage rerank 與本地 fallback，Enclave 現況較適合企業成本控制。

### 4.2 Enclave 現況

已具備：

- Hybrid Search：`app/services/kb_retrieval.py`
- RRF：canonical 與 Gateway
- Voyage rerank＋local fallback
- QueryPlan、ToolRouter、MultiStepOrchestrator
- 檔名 scoped、document head、amount expansion
- ACL-aware Redis cache

缺少：

- 通用 parent section
- sibling window
- token-budget context fitting
- 同義 multi-query
- embedding cache
- ingest-time contextual prefix

HyDE 現況：

- `app/services/kb_retrieval.py::_expand_query()` 明確停用
- 原因記載為同步阻塞約 1.1 秒，且在 Voyage＋rerank 下增益不足

因此不應只因 OpenDocuments 有 HyDE 就重新啟用。

### 4.3 採用決策

#### P0：採用 Parent Document＋Sibling＋Context Fitting

理由：

- Blind Z3／Z4 已出現跨 chunk、表格金額與長文件片段不足
- 與 Enclave canonical index 相容
- 不需增加外部 runtime

建議實作：

```text
ingest
→ chunk metadata 加 heading_path／parent_section
→ retrieval rerank 後擴 parent／sibling
→ context fitting 控 token
→ 保留原 chunk citation
```

注意：

- DB 應保存 raw chunk；parent context 只是生成上下文
- citation 仍需指向原 chunk
- parent section 不可把多文件來源混成一段

#### P1：Embedding Cache

Enclave 現有 search result cache 已比 OpenDocuments 更符合多租戶／ACL；只需考慮 query embedding L2 cache。

#### P1 實驗：Multi-query

條件：

- feature flag
- 僅模糊／口語 fact 題或 low-recall 時啟用
- 與 QueryPlan decomposition 分層
- 並行檢索＋現有 RRF

#### 不採用：OpenDocuments LLM Cross-encoder

原因：

- 每 candidate 一次 LLM，延遲／成本高
- Enclave 已有 Voyage

#### 維持停用：HyDE

只有消融證明增量後才能回來，不能因上游有功能就開啟。

### 4.4 驗收

- Parent section 單元測試：擴展、去重、citation 不丟失
- 跨 chunk 題 Hit@5／answer correctness 提升
- Multi-query on/off paired ablation
- p95 latency 與 token 使用量
- 新 Z5 hold-out，不只重跑 Z4

---

## 5. OpenAI Knowledge Retrieval：評測框架深查

### 5.1 上游真正已接線的部分

`evals/harness.py` 確實支援：

- user dataset
- local judge
- EM／F1
- Markdown／HTML report
- optional OpenAI Evals
- auto-generated dataset

### 5.2 上游宣稱但未完整接線的部分

深查發現：

- Hit@K／MRR 函式存在，但未接到主 harness
- `run_ablations` 參數存在但未使用
- pairwise judge 有 prompt／config，但沒有完整 call site
- `exclude_patterns` 在配置中存在，但 auto pipeline 沒真正使用
- auto eval 從已 ingest corpus 出題，再用同 corpus 評估，不能當 hold-out 泛化證明

所以「OpenAI KR 評測最完整」需要降級解讀：

> DX 與框架骨架完整，但部分 metrics／ablation／污染防護仍是宣稱大於接線。

### 5.3 Enclave 已經更強的部分

Enclave 已具備：

- `app/eval/metrics.py`：Hit@K、MRR、nDCG、Wilson、McNemar
- retrieval gate
- paired ablation
- answer-level deterministic span／refusal
- ACL leakage gate
- FD-* architecture gates
- Blind Z3／Z4 hold-out 與分數凍結
- source verifier
- Langfuse trace

因此不應用 OpenAI KR 取代 Enclave 現有評測。

### 5.4 採用決策

#### P0：Eval Profile 單一設定來源

借鑑 YAML DX，統一描述：

- 題庫
- corpus／manifest
- retrieval top-k
- metrics
- deterministic judge
- optional LLM review judge
- 門檻
- artifact path
- profile version／hash

目標是降低 20+ eval scripts 的操作分散，不是重寫所有評測。

#### P0：同 run 記錄 retrieval 與 answer

現在 answer correctness 應可選擇輸出：

- expected document rank
- Hit@K
- MRR
- selected chunks
- refusal reason
- generation verdict

這樣可直接分辨：

```text
文件沒找到
／文件找對但段落漏掉
／證據完整但生成漏寫
／安全門檻過拒
```

#### P1：LLM Judge 只處理 review

原則：

- 不更改 frozen 主分
- 只輸出 `review_adjudication`
- 與 source verifier 衝突時交人工

#### P2：Synthetic QA 只產草稿

禁止：

- 自動出題後直接進 release gate
- 用同 corpus synthetic 分數宣稱泛化

允許：

- 擴題草稿
- smoke fixture
- 人工審核後進正式流程

### 5.5 驗收

- artifact 含 profile ID 與 hash
- answer run 可定位 retrieval miss／generation miss
- LLM judge 不改 frozen score
- synthetic dataset 標 `draft`
- Z5 仍按 intent frozen／GT frozen／一次跑分

---

## 6. WeKnora：ASR、IM、ReAct、MCP、HITL、RBAC 深查

### 6.1 ASR

WeKnora 確實有：

- `internal/models/asr/`
- OpenAI-compatible `/v1/audio/transcriptions`
- transcript segments 與 timestamps
- 音訊檔入庫轉寫
- KB 級 ASR 設定

但它主要是「音訊文件入庫」，不是完整 voice-first APP：

- 沒有製造業即時語音確認 UX
- 沒有 TTS
- 沒有料號／金額確認
- 小程序主要是文字

Enclave 目前沒有 STT／TTS 實作。

### 6.2 IM／行動入口

WeKnora 有多種 IM adapter：

- 企業微信
- 飛書／Lark
- Slack
- Telegram
- 釘釘
- Mattermost
- QQ
- 雲之家等

但未見台灣產品最常用的 LINE adapter。

Enclave：

- Web 控制面成熟
- `mobile/` 為 Experimental
- 無語音、掃碼與正式 IM adapter

### 6.3 ReAct

WeKnora 的 ReAct 是實際接入 Chat／IM 的產品路徑：

- `internal/agent/engine.go`
- `internal/agent/act.go`
- `internal/agent/observe.go`
- `internal/agent/tools/`

Enclave 雖有 `app/agent/react_loop.py`，但：

- 未接正式 Chat
- 不是完整 LLM tool-selection loop
- 主要由測試／eval 使用

因此 Enclave 的 ReAct 目前不能視為等價產品能力。

### 6.4 MCP

WeKnora 有：

- MCP Client
- OAuth
- server manager
- Agent tools
- 設定 UI
- 外部 MCP server package

Enclave 的 `app/services/mcp_tools.py` 只是固定產生工具描述的 discovery stub：

- 不連 MCP server
- 不做 OAuth
- 不執行工具

所以 Enclave 目前沒有 production MCP runtime。

### 6.5 HITL

WeKnora 的 MCP HITL 有：

- tool approval gate
- Redis 跨副本 resolve
- 可修改 JSON 參數後批准
- timeout
- Chat approval card

Enclave 有兩種不同能力：

1. 文件 Review Queue：產品級
2. Agent Approval API：有後端骨架，但未接 Chat／UI

正式報價、合約、Fixed Form 的多級簽核，兩邊都沒有完整成品。

### 6.6 RBAC

WeKnora 有 workspace RBAC，但 Enclave 更適合製造業：

- tenant
- department
- object-level authorization
- connector ACL
- deny precedence
- DB RLS

決策：

> Enclave 必須保持權限權威；WeKnora 只能是受授權的 sidecar／工具執行參考。

### 6.7 採用決策

#### 採用模式

- ASR 入庫 pipeline
- IM adapter 架構
- MCP manager／OAuth／tool registration
- MCP HITL gate 與 approval card
- ReAct engine 的 act／observe／budget 模式

#### Enclave 原生建置

- STT／TTS Interaction Gateway
- 語音關鍵欄位確認
- LINE
- 職能模組 Router
- Fixed Form
- 正式業務簽核狀態機
- 權限與 audit

#### 不採用

- WeKnora RBAC 取代 Enclave
- WeKnora 小程序直接當製造業 APP
- 整包替換 Enclave Chat
- 將現有 Enclave MCP stub 宣稱為完成

### 6.8 驗收

- 音訊轉寫先進 draft，不可直接回答
- tool call 必帶 AuthorizationContext
- mutating tool 預設需 approval
- approve／reject 可 resume、冪等、超時、fail-closed
- 關鍵金額／料號需使用者確認
- Mobile／IM 不得繞過 Enclave PEP

---

## 7. OpenKB：長文、Wiki、Skill、Know-how 深查

### 7.1 上游能力

OpenKB 確實有：

- `pageindex_threshold: 20`
- 長 PDF 走 PageIndex tree
- query 時按頁取內容
- 文件編譯成 summaries／concepts／entities
- semantic lint
- Skill Factory
- skill iteration／rollback／eval

### 7.2 重要限制

OpenKB 沒有：

- 多租戶
- RBAC
- STT
- knowledge card schema
- draft／published 審核流程
- Enclave 式 FusionPolicy
- 企業級 source tombstone／撤權

Wiki recompile 可能覆蓋人工內容，不能直接當企業權威知識庫。

### 7.3 與 Enclave 的關係

Enclave 已有：

- canonical pgvector
- WeKnora Wiki
- WikiRevision
- clause projection
- Review Queue
- source verifier
- FD-* gates

Enclave 的 `clause_projection` 是 know-how card 的更適合範本：

```text
來源
→ LLM 結構化
→ DocumentArtifact
→ 審核／Wiki 投影
→ compiled retrieval
```

### 7.4 採用決策

#### P0：Enclave 原生 Know-how Card

建議流程：

```text
音訊
→ STT
→ knowhow_draft
→ 結構化知識卡
→ SOP 衝突檢查
→ 人工審核
→ approved_knowhow
→ 索引／Wiki
```

OpenKB 只借：

- compiler prompt／concept planning
- semantic lint
- Skill evaluator

#### P2：PageIndex Optional Specialist

只適用：

- 長設備手冊
- 20 頁以上 manual
- 需要頁範圍推理

必須：

- 預設 OFF
- 寫 `DocumentArtifact(pageindex_tree)`
- 不取代 canonical index
- 通過 ablation 才進 fan-out

#### 不採用

- OpenKB 整包 sidecar 作第二權威 Wiki
- 未審語音直接 `openkb add`
- OpenKB query 取代 Enclave chat

### 7.5 驗收

- draft 不可被 RetrievalFacade 命中
- approved 才索引
- SOP 與 know-how 衝突時 SOP 優先並顯示差異
- 知識卡包含適用設備、風險、審核者與版本
- PageIndex 需在長 manual ablation 證明增量

---

## 8. OpenRAG：Langflow、MCP、Docling、Approval 深查

### 8.1 Langflow／Agentic RAG

OpenRAG 的 Langflow 確實是產品主路徑，不只是 demo：

- `flows/openrag_agent.json`
- `flows/ingestion_flow.json`
- 自訂 components
- Langflow container
- 前端預設 Langflow endpoint

Enclave 已有產品級：

- QueryPlan
- ToolRouter
- MultiStepOrchestrator
- RetrievalTrace
- FD-QUERYPLAN

因此引入 Langflow 會形成第二套編排 runtime，增加：

- 權限傳遞風險
- trace 分裂
- flow 版本維護
- sidecar 運維
- 測試重複

決策：

> 不為了「可視化」引入 Langflow；需要營運可調時，先做 data-driven QueryPlan／module config。

### 8.2 MCP

OpenRAG 有 production FastMCP：

- `/mcp`
- OpenAPI endpoint 自動暴露
- auth header 處理
- read-only search／chat tools
- multipart ingest 明確排除

這對 Enclave 的價值高，但不需要 Langflow。

決策：

- P1：可建立 read-only FastMCP server
- P2：MCP client＋allowlist＋ApprovalGate
- 大量文件仍走 HTTP／connector，不走 MCP

### 8.3 Docling

OpenRAG 確實有產品級 Docling Serve integration：

- polling service
- Langflow component
- health UI
- K8s sample
- 長 OCR 不占 flow slot

Enclave 未整合 Docling，現有解析棧為：

- RAGFlow DeepDoc
- cloud OCR
- pdfplumber／PyMuPDF／pytesseract
- LlamaParse

決策：

- 不因 OpenRAG 有 Docling 就直接加服務
- 先用表格／掃描 corpus 做 parser ablation
- 若 Docling 對表格、版面或多格式有實證增量，再作 Enterprise optional sidecar

### 8.4 Approval

OpenRAG flow 中未見真正 human approval node。

因此不能用 OpenRAG 解決 Enclave Fixed Form 審核；Enclave 應擴展自身 Review Queue／AgentApproval。

### 8.5 採用決策

- 不採 Langflow runtime
- 借 FastMCP server 模式
- 條件式採 Docling Serve
- Fixed Form／approval 原生 Enclave
- 可視化編排低優先

---

## 9. PipesHub：連接器、OAuth、ACL、增量同步深查

### 9.1 上游實際能力

PipesHub 約有：

- 43 個 `connector.py`
- 37 個 GA factory entries
- 7 個 beta connector

成熟能力集中在：

- SharePoint／OneDrive
- Google Drive
- BookStack
- Slack
- S3／GCS／Azure storage
- Salesforce／ServiceNow
- 部分 SQL／資料倉

但 connector enum、factory、原始碼與 live integration test 的數量不同，不能把 enum 數量直接當 GA。

### 9.2 Enclave 實際吸收

Enclave 已有：

- PipesHubHTTPAdapter
- connector sync lifecycle
- connector 名稱映射
- ACL 投影
- BookStack live ACL
- nas_smb 原生認證

目前可誠實宣稱：

- nas_smb PASS
- BookStack PipesHub sync／ACL PASS
- PipesHub token refresh

不可宣稱：

- 30+／40+ 連接器皆 GA
- SharePoint／Drive 已完成
- Webhook 即時同步
- ERP 原生整合
- PipesHub LOCAL_FS 等於 Enclave NAS

### 9.3 關鍵斷點

雲端 connector 的 resource 若沒有本機 `file_path`，目前 `materialize_to_documents()` 不會自然進 Enclave canonical／RAGFlow。

因此即使 PipesHub 已完成 resync，也不等於：

```text
SharePoint／Drive
→ Enclave Document
→ RAGFlow
→ canonical chat
```

這條下載／materialize 管線仍需在真實客戶場景施工。

### 9.4 採用決策

#### 維持現況

- NAS 繼續走 Enclave native
- BookStack 保留已驗證路徑

#### 需求驅動

每一個新 connector 必須：

1. 真實 OAuth
2. sync records > 0
3. ACL leakage = 0
4. delete／rename／revocation
5. incremental sync
6. empty async result 不誤刪
7. 是否 materialize 到 canonical 的明確決策
8. connector-specific artifact

#### 延後

- ERP／CRM
- SQL warehouse
- beta connectors
- Agent Sandbox

除非有明確客戶與資料分類 ADR。

---

## 10. 修正後的優先順序

### P0：準確率與可診斷性

1. Parent Document＋Sibling＋Context Fitting
2. Eval Profile 單一設定來源
3. answer run 同時記錄 retrieval rank／chunks／refusal
4. 新 Z5 hold-out

### P1：製造業產品工作層

1. STT／TTS Interaction Gateway
2. Enclave Mobile／PWA voice-first
3. 職能模組 Router
4. Fixed Form Schema
5. 關鍵欄位確認
6. Review／Approval 狀態機

可參考：

- WeKnora ASR／IM／MCP／HITL／ReAct
- OpenRAG FastMCP

但由 Enclave 掌控身分、權限、來源、表單與審核。

### P2：Know-how 與長文件

1. Know-how Card
2. draft isolation
3. authority tier
4. SOP conflict detection
5. OpenKB compiler／semantic lint 借鑑
6. PageIndex 長 manual ablation

### P3：需求驅動整合

1. 客戶真正使用的 SharePoint／Drive
2. connector materialize
3. read-only MCP
4. mutating MCP＋HITL
5. Docling parser ablation

### 明確不做

- 不整包引 OpenDocuments
- 不恢復 HyDE 預設
- 不用 OpenAI KR auto eval 取代 Blind Z
- 不用 WeKnora RBAC 取代 Enclave
- 不整包引 OpenKB
- 不引 Langflow 作第二套主編排
- 不先做 40 個 connector 再找客戶

---

## 11. 各能力的完成定義

### 11.1 檢索能力

完成不等於程式存在，而是：

- feature flag
- on/off ablation
- retrieval metrics
- answer correctness
- citation 不回退
- latency／token budget
- Z5 泛化

### 11.2 語音／APP

完成不等於 STT 回文字，而是：

- 噪音場景可用
- 專有詞／料號可校正
- 關鍵欄位確認
- 權限不繞過
- 任務可中斷續作
- 高風險操作需批准

### 11.3 Fixed Form

完成不等於 LLM 生成 Markdown，而是：

- schema
- required fields
- deterministic calculations
- provenance
- preview
- version
- approval
- formal export

### 11.4 Know-how

完成不等於錄音轉文字，而是：

- draft isolation
- structured card
- SOP conflict
- reviewer
- effective version
- revocation
- source quote

### 11.5 Connector

完成不等於 adapter 有名稱，而是：

- real OAuth／credential
- records
- ACL
- delta
- delete／revoke
- canonical or federated boundary
- live certification artifact

---

## 12. 已發現的文件與程式不一致

後續應另案修正，但本稽核不直接改寫：

1. `docs/TECHNICAL_BENCHMARK.md`
   - 寫 Enclave「完全沒有內建評測框架」已過時
   - OpenAI KR「最完整」需加註部分 metrics／ablation 未接線

2. `app/services/kb_retrieval.py`
   - HyDE 已明確停用
   - 部分設定／驗證文件仍像是可啟用

3. `app/services/mcp_tools.py`
   - 名稱為 MCP discovery，但實際是 placeholder，不應當產品能力

4. PipesHub connector capability
   - adapter capability 宣稱 upstream webhook／delta，不等於 Enclave 已接 webhook

5. OpenRAG
   - 有 Agentic／MCP／Docling，但沒有預期中的 human workflow approval

---

## 13. 風險

### 13.1 架構複雜度

若同時引入：

- OpenDocuments runtime
- OpenKB runtime
- Langflow
- Docling
- MCP
- PipesHub 全連接器

Enclave 會形成過多索引、編排與治理來源，反而降低可靠性。

控制方式：

- 原生 port 優先
- sidecar 必須 optional
- canonical index 不變
- 單一 PEP
- 單一 approval authority

### 13.2 「接線即價值」假綠

過去已有 Graph／RAPTOR／template 等能力接線後 `NO_VALUE`。

所有新能力必須先證明：

- 精度提升
- 延遲合理
- 成本可接受
- 權限不回退
- 操作體驗更好

### 13.3 開源版本與維護

直接 copy 上游程式會產生：

- 安全修補落差
- 版本漂移
- 授權與 SBOM
- 難以回併

因此以設計模式借鑑、薄 adapter 或原生契約 port 為主。

---

## 14. 最終決策

經過原始碼與 Enclave call site 再確認，先前的六點建議可以保留，但必須採以下版本：

1. **OpenDocuments：採檢索模式，不採整包。**
2. **OpenAI KR：採設定與報告 DX，不採其 auto eval 作泛化證明。**
3. **WeKnora：採 Agent 執行面設計模式，不採其 RBAC／UI 取代 Enclave。**
4. **OpenKB：採編譯／lint／PageIndex 思路，不作第二權威知識庫。**
5. **OpenRAG：不採 Langflow；條件式採 FastMCP／Docling。**
6. **PipesHub：維持 sidecar，每一 connector 需求驅動、逐一認證。**

最重要的原則：

> Enclave 的競爭力不在於安裝最多開源元件，而在於把少數真正有效的能力，納入同一套權限、來源、拒答、審核與評測契約。

這份稽核支持繼續補強，但不支持「六套專案全部植入」。

---

## 15. 關鍵證據索引

### OpenDocuments

- `github_projects/OpenDocuments/packages/core/src/rag/multi-query.ts`
- `github_projects/OpenDocuments/packages/core/src/rag/parent-doc.ts`
- `github_projects/OpenDocuments/packages/core/src/rag/retriever.ts`
- `github_projects/OpenDocuments/packages/core/src/rag/context-window.ts`
- `github_projects/OpenDocuments/packages/core/src/rag/eval.ts`

### OpenAI Knowledge Retrieval

- `github_projects/openai-knowledge-retrieval/evals/harness.py`
- `github_projects/openai-knowledge-retrieval/evals/generator/auto_pipeline.py`
- `github_projects/openai-knowledge-retrieval/evals/metrics/retrieval.py`
- `github_projects/openai-knowledge-retrieval/evals/metrics/qa.py`

### WeKnora

- `github_projects/WeKnora/internal/models/asr/`
- `github_projects/WeKnora/internal/im/`
- `github_projects/WeKnora/internal/agent/engine.go`
- `github_projects/WeKnora/internal/agent/approval/gate.go`
- `github_projects/WeKnora/internal/mcp/`

### OpenKB

- `github_projects/OpenKB/openkb/indexer.py`
- `github_projects/OpenKB/openkb/agent/query.py`
- `github_projects/OpenKB/openkb/agent/compiler.py`
- `github_projects/OpenKB/openkb/agent/linter.py`
- `github_projects/OpenKB/openkb/skill/evaluator.py`

### OpenRAG

- `github_projects/openrag/flows/`
- `github_projects/openrag/src/mcp_http/server.py`
- `github_projects/openrag/src/services/langflow_mcp_service.py`
- `github_projects/openrag/flows/components/docling_remote.py`

### PipesHub

- `github_projects/pipeshub-ai/backend/python/app/connectors/`
- `github_projects/pipeshub-ai/backend/python/app/connectors/core/factory/connector_factory.py`
- `github_projects/pipeshub-ai/backend/python/app/config/constants/arangodb.py`

### Enclave

- `app/services/kb_retrieval.py`
- `app/services/query_plan.py`
- `app/services/multi_step_orchestrator.py`
- `app/services/retrieval_facade.py`
- `app/services/source_verifier.py`
- `app/services/mcp_tools.py`
- `app/agent/react_loop.py`
- `app/agent/review_queue.py`
- `app/gateway/adapters/weknora_http.py`
- `app/gateway/adapters/pipeshub_http.py`
- `app/eval/metrics.py`
- `scripts/eval_answer_correctness.py`
- `docs/MANUFACTURING_KNOWLEDGE_ASSISTANT_PRODUCT_VISION.md`
- `docs/CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md`
- `docs/OPEN_GATES.md`

---

*本文件只記錄經原始碼與現有 artifacts 可證明的能力；未將 README、feature 名稱或 adapter 存在本身視為產品完成。*

