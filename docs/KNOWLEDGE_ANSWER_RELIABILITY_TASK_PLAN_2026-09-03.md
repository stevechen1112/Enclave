---
title: "Enclave Knowledge Answer Reliability Task Plan"
document_type: "implementation_plan"
language: "zh-TW"
date: "2026-09-03"
version: "1.2"
status: "implemented, reviewed and deployed"
scope: "Knowledge Kernel and Ask; not Input I9 replacement"
source_reference: "AIHR技術成果與Enclave通用知識庫轉用建議_20260903.md"
---

# Enclave Knowledge Answer Reliability Task Plan

## 0. 文件目的與執行決策

本計畫承接 AIHR 已驗證的企業問答經驗，但不搬移 AIHR 專案、不建立第二條 RAG 主幹，也不重做 Enclave 已完成的 K0–K10、Input I9、Knowledge Unit、KB revision、ACL、RetrievalFacade、SourceVerifier、Shadow 與 Pack 基礎。

本輪唯一核心目標是：

> 讓 Enclave Live Ask 在生成答案以前，先由伺服器以同一份、可追蹤的 Evidence Decision 判斷證據是否對題、適用、完整、無衝突且足以回答；模型只能在核准的 Answer Plan 內表達，不得自行補造公司事實。

執行原則：

1. 先完成 KQ0 基線與處置矩陣，再進入程式修改。
2. 新能力先 contract、再 adapter、再 shadow、最後才 enforce。
3. 每一個完整 phase 完成後必須獨立 Code Review；Review 未通過不得開始下一 phase。
4. 李永仁的 Input 第二輪真實測試與本計畫分線進行；KQ3 前不得改變正式使用者答案。
5. 任何既有責任若已有 canonical owner，只能擴充或收斂，禁止建立平行 aggregate、平行 revision、平行 retrieval 或平行 citation。
6. AIHR 的題目、客戶名、固定答案、HR 文件家族與手工特判不得進入 Enclave core。
7. 歷史啟動規則已履行：Owner 於 2026-09-03 指示開工，KQ0–KQ7 隨後完成實作、Review 與 production 部署。

## 1. 與既有計畫的關係

本計畫是 `ENCLAVE_ENTERPRISE_KNOWLEDGE_BASE_ENHANCEMENT_PLAN.md` 的「Live Ask 決策收斂增量計畫」，不是新的知識庫總體架構。

| 既有成果 | 本計畫處置 |
|---|---|
| K0–K10 核心模型、版本、發布與評測防線 | 沿用，不重新命名或複製 |
| Input I9 多模態來源處理 | 沿用；只在 KQ4 消費其 DerivedArtifact、EvidenceSpan 與 Knowledge Unit 投影 |
| QueryPlan／QuerySpec 骨架 | 擴充解析能力與 preservation，不新增第二個 query router |
| EvidenceContract／EvidenceOrchestrator | 收斂為 Live Ask 唯一 pre-generation decision owner |
| `retrieval_coverage.py` | 保留相容 adapter；完成 parity 後退場為 legacy heuristic，不再擁有最終決策 |
| RetrievalFacade／FusionPolicy | 唯一檢索主幹；所有 Pack 與 relation expansion 都必須經 ACL/revision 二次檢查 |
| KnowledgeUnitRecord／KnowledgeUnitRevision／Release | canonical knowledge authority；typed knowledge 以擴充或 revision-scoped projection 承接 |
| SourceVerifier | 保留為回答後 defense in depth，不再負責補救生成前漏答 |
| PackContribution／PackRegistry | 擴充標準 contributions；不允許 Pack 直接改寫 core decision 或繞過權限 |
| ADR-014、ADR-018、ADR-020 | 繼續有效；本計畫只新增必要 amendment 或 mapping ADR |

### 1.1 既有未解除 Gate 的關係

本計畫的開發完成判定只採技術證據；陌生題盲測與客戶書面確認可由 QA／營運另行執行，不是 KQ7 開發或 enforce 的阻斷條件。其餘技術發布檢查仍包含：

- `KB-SCALE-01`：符合實際部署 profile 的容量、品質、尾延遲與成本證據。
- `KB-UX-01`：獨立人員完成角色、權限、來源卡、錯誤及手機瀏覽器驗收。
- `KB-SHADOW-01`：正式 tenant、最終映像、read-only mutation sentinel 的 Shadow 證據。
- `KB-OPS-01`：feedback、freshness、trace privacy、backup/restore/rollback 與 RTO operator 證據。

KQ gate 證明「新 Answer Decision 能力本身」；KB gate 證明「整體 Knowledge 產品可發布」。兩者不能互相替代。

## 2. 現況基線與已確認差距

### 2.1 已具備能力

- 多租戶、tenant/department/source ACL、deny/tombstone 與 RLS 邊界。
- SourceAsset、AssetRevision、DerivedArtifact、EvidenceSpan 與多模態 Input pipeline。
- Knowledge Unit、immutable revision、candidate/active release、KB revision 與 rollback。
- catalog、chunk、structured、procedure、compiled 等多臂 RetrievalFacade。
- QuerySpec 欄位、AnswerSlot、EvidenceContract、structured/procedure resolver、AuthorityPolicy 與 SourceVerifier。
- Pack manifest、tenant eligibility、knowledge provider、projector、permission、review、route、workflow 等 contributions。
- sealed evaluation、read-only production shadow、release identity 與 browser acceptance 基礎。

### 2.2 程式核對後的真實差距

1. `EvidenceContract` 雖定義 `value_type`、`source_scope`、`temporal_requirement`、`kb_revision_id` 等資料，但現行 `evaluate()` 尚未完整執行型別、來源範圍、時間條件、exact revision、cardinality 與 relation closure。
2. `EvidenceOrchestrator` 已存在，但 Live Ask 目前主要呼叫 `retrieval_coverage.assess_retrieval_coverage()`；兩套 decision 還沒有收斂成唯一權威。
3. 現行 coverage 仍依少量中文關鍵詞與 regex 判斷欄位是否出現在候選文字，對複合題、否定、定義、判斷、比較、完整清單、條件與多輪有明顯上限。
4. SourceVerifier 位於生成後；能攔截部分無來源 claim，但不能補出漏掉的必要面向，也不能可靠建立正確的部分答案。
5. Knowledge Unit 已有 canonical revision 與 applicability，但通用 typed payload、relation closure 與 closed-list completeness 尚未成為 Live Ask 標準輸入。
6. Pack contract 尚未明確擁有 RequirementCompiler、ApplicabilityProvider、ResolverProvider、AnswerRenderer 與 InvariantContribution 等知識決策擴充點。
7. UI 尚未將「完整回答／部分回答／缺少條件／來源衝突／系統執行失敗」視為不同產品狀態完整呈現。

### 2.3 宣稱邊界

- AIHR 的 61 題是已知 incident regression，不是 Enclave 跨公司盲測。
- AIHR 45/61 可接受、16 題未達標，不能直接推論 Enclave 上線後品質。
- AIHR typed graph 與規則 A 提供可移植技術證據，不是可直接複製的產品模組。
- Enclave 既有 K0–K10「已施工」不等於所有正式 Shadow、sealed holdout、容量與獨立驗收均已解除。
- 本計畫完成前，只能宣稱「建立可驗證回答決策能力」，不能宣稱所有領域答案都正確。

## 3. 能力處置矩陣

| 能力 | Canonical owner | 處置 | 禁止事項 | 退場／完成條件 |
|---|---|---|---|---|
| 問題規劃 | `query_plan.py` | 擴充為可插拔 parser | 新建 AIHR query service | sync/stream 共用同一 QuerySpec |
| 必答需求 | `EvidenceContract` | 擴充 AnswerRequirement 語意 | Pack 自行放行答案 | 所有 required facets 有具名結果 |
| 最終證據決策 | `EvidenceOrchestrator` | 升級為唯一 owner | `retrieval_coverage` 與 orchestrator 各自決定 | Live Ask 只消費一個 EvidenceDecision |
| Legacy coverage | `retrieval_coverage.py` | adapter／shadow comparator | 繼續直接控制正式答案 | parity 完成並移除最終決策權 |
| 檢索 | `RetrievalFacade` | 擴充 exact/short-value/relation arms | Pack 直查未過濾索引 | 所有候選帶 tenant/revision/source refs |
| Typed knowledge | `KnowledgeUnitRevision` | 擴充 payload／projection | 第二套 atom authority | 可回到 EvidenceSpan 與 exact revision |
| Knowledge relation | Knowledge Unit projection | 缺口確認後新增 revision-scoped relation | 建立獨立 AIHR graph 真相 | relation 可重建、可撤權、可按 release 查詢 |
| 適用性／權威 | `AuthorityPolicy`＋Knowledge Unit applicability | 擴充情境矩陣 | 用單一 ranking 隱藏衝突 | 同事項同 scope 才能判 conflict |
| 引用 | `CitationBuilder`／EvidenceSpan | 沿用與擴充 | renderer 自造 citation | 每個 claim 有可存取 exact source ref |
| 回答後驗證 | `SourceVerifier` | 保留第二道防線 | 把 provider failure 算成正確拒答 | claim-ID diff 與 deterministic checks 完成 |
| 領域差異 | `PackContribution` | 擴充標準 provider contracts | core 出現 HR／客戶特判 | 卸載 Pack 後 contributions 一起 fail closed |
| 評測 | 既有 shadow/eval runtime | 擴充六階段 trace | 測試失敗被總分掩蓋 | deterministic regression 與分項指標 |
| UX | Ask 與 evidence drawer | 擴充 decision/gap/conflict 顯示 | 只顯示「不知道」或技術錯誤 | 使用者可理解答案狀態與下一步 |

## 4. 目標資料與決策契約

### 4.1 三個正交狀態

```text
EvidenceState
  complete | partial | absent | conflict | insufficient_context

ResponseAction
  answer | answer_partial | clarify | abstain | escalate

ExecutionStatus
  ok | provider_error | schema_error | timeout | pack_failure | internal_error
```

硬性規則：

- ExecutionStatus 非 `ok` 時不得偽裝成 `EvidenceState=absent`。
- `absent` 只有在 `reviewed_scope` 明確且檢索／驗證正常完成時才能核發。
- `conflict` 只適用於同一事項、同一實體、同一適用範圍及重疊有效期間。
- `insufficient_context` 只問會改變答案的最小必要問題。
- `partial` 必須輸出已回答項目及具名缺口，不得把整題清空。

### 4.2 QuerySpec／AnswerRequirement

```text
QuerySpec
  query_id, original_question, operation, requirement_shape
  entities[], requested_facets[], operators[]
  source_scope, temporal_scope, authority_constraints
  expected_cardinality, completeness_mode, risk_class
  ambiguity[], confidence, preserved_tokens

AnswerRequirement
  requirement_id, label, shape, required
  value_type, entity_binding, source_scope
  temporal_requirement, authority_requirement
  minimum_values, expected_cardinality, exhaustive
  required_relations[], allowed_derivation[]
```

必須原樣保留人名、設備／產品代碼、數字、日期、否定詞、比較對象與使用者指定來源。解析器可由 deterministic rules、模型或 Pack 提案，但 schema validation、scope 與最終 requirement ownership 在伺服器。

### 4.3 TypedKnowledgeUnit／KnowledgeRelation

優先沿用 `KnowledgeUnitRevision`：

```text
TypedKnowledgePayload
  kind, subject, predicate, value, value_type, statement
  conditions[], exceptions[], applies_to[], topic_tags[]
  entity_ids[], authority_class, effective_range, risk_class
  source_span_id, exact_quote, section_path, content_hash

KnowledgeRelation
  relation_id, tenant_id, source_unit_revision_id
  target_unit_revision_id, relation_kind
  provenance, confidence, review_state, schema_version
```

初始 relation kinds：

- `condition_of`
- `exception_of`
- `member_of`
- `next_step`
- `same_record`

關係不得跨 tenant，不得指向未獲准或不可存取 revision；來源撤權、tombstone、release 切換後必須同步失效。資料表是否新增須在 KQ0 mapping ADR 確認，若既有 projection payload 足夠則不新增表。

### 4.4 EvidenceDecision／AnswerPlan

```text
EvidenceDecision
  decision_id, query_spec_version, contract_version
  evidence_state, response_action, execution_status
  verified_claims[], answered_requirements[]
  missing_requirements[], conflicts[], near_evidence[]
  reviewed_scope, reason_codes[], trace_id
  kb_revision_id, knowledge_release_id, pack_versions

VerifiedClaim
  claim_id, requirement_id, claim_type, value, rendered_statement
  evidence_refs[], derivation, applicability, confidence

AnswerPlan
  direct_answer, sections[], verified_claim_ids[]
  gaps[], clarifying_questions[], conflicts[]
  warnings[], citations[], rendering_policy
```

模型若負責潤飾，只能改寫 AnswerPlan 中已核准 claims。新增人名、數字、日期、範圍、條件或結論時，claim-ID diff 必須拒絕輸出並退回 deterministic renderer。

## 5. 目標執行流程

```text
User question
  → QuerySpec proposal
  → schema/preservation/ambiguity validation
  → AnswerRequirement compilation
  → RetrievalFacade multi-arm retrieval
  → tenant/ACL/revision/release deny-first filtering
  → typed candidate admission
  → relation expansion
  → applicability/authority/temporal/conflict evaluation
  → coverage/cardinality/completeness evaluation
  → one EvidenceDecision
  → AnswerPlan
  → deterministic render or constrained paraphrase
  → SourceVerifier defense in depth
  → citation drawer + decision trace
```

同步回答與串流回答必須使用相同 QuerySpec、EvidenceDecision 與 AnswerPlan。Enforce 模式下，在 claim 驗證前不得先串流未核准公司事實。

## 6. 分階段工作計畫

## KQ0：基線凍結與 AIHR→Enclave Mapping

### 目標

建立可重現的現況真相，決定每項 AIHR 能力的 canonical owner，避免後續重做與污染。

### 工作

1. 凍結目前正式與測試環境的 Ask API schema、sync/stream 行為、release identity、prompt/model、KB revision 與 Pack versions。
2. 建立至少下列基線案例：直接事實、完整清單、部分答案、無答案、缺條件、衝突、比較、程序、表格同列、錯 scope、錯 revision、provider failure、多輪。
3. 逐項完成 AIHR type/relation/service 到 Enclave owner 的 disposition：reuse、extend、new、pack、reject。
4. 掃描 core 是否已有客戶名、題號、完整題句或領域公式；建立禁止清單。
5. 核對 `retrieval_coverage`、`EvidenceOrchestrator`、SourceVerifier 在 sync/stream 中的真實呼叫圖。
6. 決定 relation 使用既有 JSON projection 或新增 revision-scoped model，形成 ADR amendment。

### 交付物

- `docs/adr/ADR-0xx-aihr-enclave-knowledge-decision-mapping.md`
- `artifacts/knowledge/KQ_BASELINE_MANIFEST.json`
- `docs/knowledge/KQ_BASELINE.md`，只保存基線說明、重現方式、敏感資料邊界與前述 artifact manifest reference，不複製 baseline JSON。
- `docs/knowledge/KQ_CAPABILITY_DISPOSITION.md`
- `artifacts/knowledge/` 下的呼叫圖、baseline outputs、hash manifest 與 known-failure registry；`docs/` 只保存說明與相對 manifest reference。

### 測試

- 現行 baseline 可重放。
- sync/stream/schema snapshot 完整。
- core contamination scan 為 0；允許項目必須有明確 waiver。
- baseline 不修改 tenant 資料。

### Code Review Gate：`KQ-BL-01`

- 所有 proposed 新 aggregate 都有「為何既有 owner 無法承接」的證據。
- baseline 綁定 exact source commit、image、KB revision、Pack version。
- 無法重現目前 Ask 時停止施工，不得進 KQ1。

## KQ1：通用契約與相容 Adapter

### 目標

建立向後相容的 QuerySpec、AnswerRequirement、EvidenceDecision 與 ExecutionStatus 契約，不接管 Live Ask。

### 工作

1. 版本化 QuerySpec，加入 requirement shape、facets、source scope、cardinality、ambiguity 與 preservation validation。
2. 擴充 EvidenceContract，真正執行 value type、entity、source scope、temporal、authority、exact revision、minimum/expected cardinality、relation closure 與 allowed derivation。
3. 將 EvidenceState、ResponseAction、ExecutionStatus 分為三個欄位及列舉。
4. 提供 legacy coverage → EvidenceDecision adapter，保留既有 API schema。
5. 定義 reason code、具名 gap、conflict 與 reviewed scope schema。
6. 加入資料最小化與 trace redaction；不得把完整機密內容寫入一般 log。

### 測試矩陣

- 正確／錯誤 value type。
- 正確／錯誤 entity binding。
- 正確／錯誤 tenant、department、source、KB 與 revision scope。
- temporal 未到期、已過期、日期缺失與邊界日。
- minimum、exact、exhaustive 與 closed-list cardinality。
- provider/schema/timeout/pack failure 不得轉為 absent。
- 舊呼叫端 compatibility tests。

### Code Review Gate：`KQ-CONTRACT-01`

- 契約 domain-neutral，core 掃描 0 客戶／HR 特判。
- 所有新增欄位有 schema version、default 與 backward compatibility。
- fail-closed 不得把可回答證據全部誤拒；正負例都必須存在。
- 未接 Live Ask，不得改變正式輸出。

## KQ2：唯一 Evidence Decision Engine

### 目標

把選取、適用性、完整性與衝突收斂成單一 server-owned decision；仍先由測試與離線 runner 使用。

### 工作

1. 將 `EvidenceOrchestrator` 升級為唯一 decision API。
2. 依序執行 candidate admission、ACL/revision recheck、applicability、authority、temporal、relation closure、coverage、cardinality 與 conflict。
3. 明確區分 `near_evidence` 與 `verified_claims`；相似但不回答本題的內容不得成為 claim。
4. 建立 deterministic aggregate／日期／集合／同列／程序 derivation registry。
5. 建立同一回答 claims 的一致性檢查。
6. 建立 stage trace：parse、retrieve、select、applicability、completeness、conversation。

### 測試矩陣

- 有答案、部分答案、無答案、缺條件、真衝突、假衝突。
- 相鄰主題、同章標題與短泛詞不得放行。
- 候選中存在可接受證據時不得宣告 absent。
- 不同廠區／產品／專案／版本的差異不得誤判全域衝突。
- structured ambiguity 與 procedure ambiguity 必須 fail closed。
- decision deterministic replay；相同輸入得到相同 decision hash。

### Code Review Gate：`KQ-DECISION-01`

- repository 內只有一個最終 EvidenceDecision owner。
- RetrievalFacade、ACL、KB revision 與 deny-set 無繞過路徑。
- legacy heuristic 只能作輸入或比較，不得覆寫 decision。
- 每個失敗案例可定位到單一 stage 與 reason code。

## KQ3：Live Ask Shadow 與決策差異量測

### 目標

在 Live Ask 旁路執行新決策，不改使用者答案、不新增 conversation/message、不中斷李永仁既有測試。

### 工作

1. 新增 tenant allowlist 與 `off/shadow/enforce` flag；預設 `off`。
2. sync 與 stream 共用同一 shadow adapter。
3. 記錄 legacy/new decision、false reject 候選、false accept 候選、stage latency、provider error 與 decision hash。
4. Shadow process 使用 read-only transaction／mutation sentinel；不得寫 cache、usage 或正式 feedback。
5. decision diff 經獨立、out-of-band writer 寫入 tenant operational DB 之外的 evaluation artifact／telemetry store；不得以 tenant DB table、conversation、message、正式 feedback、usage 或一般 cache 承接。
6. 該 store 必須 append-only，採傳輸中與靜態加密，設定 tenant-scoped access control、明確 retention class／到期清除、legal hold 例外與 purge audit。一般欄位優先只保存 tenant-scoped pseudonymous IDs、hash、reason codes 與 latency；必要片段另行加密、最小化並限制角色。
7. append-only 代表已寫入 run/case 不得 update 或覆寫；更正只能新增 superseding record 並連回原紀錄。到期清除只能由 retention／legal-hold 流程執行且留下不含敏感本文的稽核紀錄。
8. 管理端差異檢視只透過授權服務唯讀查詢該 store，顯示原回答、舊 decision、新 decision、gaps、conflicts、sources 與 trace；每次讀取重新檢查 tenant、角色與來源可見性，不得把受限內容複製回 tenant DB。
9. artifact writer 故障不得改變或阻塞使用者答案，也不得 fallback 寫入 tenant DB；本次 Shadow case 必須標示 telemetry failure，不能納入有效量測分母。
10. 建立 kill switch；任何 latency、error 或資料外洩異常可立即關閉。
11. 首次正式 tenant Shadow 前，先凍結不可覆寫的 threshold manifest：樣本與排除規則、false rejection／false acceptance 的分子分母與最高門檻、各 stage 及端到端 latency overhead 的 P50/P95/P99 門檻、provider/schema/timeout/pack failure 門檻、sync/stream parity 與停止條件。看到首跑結果後不得回改門檻；任何修訂須產生新版本並重跑。

### 量測

- decision agreement rate。
- false rejection／false acceptance 分開呈現。
- complete→partial、answer→abstain、absent→answer 等轉換矩陣。
- parse/retrieve/select/applicability/completeness/render 各階段 P50/P95/P99。
- provider/schema/timeout/pack failure 率。
- sync/stream parity。

### Code Review Gate：`KQ-SHADOW-01`

- tenant mutation 0。
- 至少 30 個真實案例，涵蓋至少 2 個不同 subject，並含至少 4 個 deny／forbidden 負例；案例 manifest、subject 定義、執行者與 release identity 在首跑前凍結。
- 首跑前的 threshold manifest 已凍結，且 false rejection、false acceptance、latency overhead、execution failure 與 sync/stream parity 均依預先門檻判定；不得以首跑結果回調門檻取得 PASS。
- 使用者可見回答與 KQ0 baseline 一致。
- Shadow 關閉後，請求路徑不再執行 shadow decision、diff 或 provider/model 呼叫，也不再產生模型成本；依法或依政策保留的既有 artifact 仍依 retention 占用加密儲存，直到到期清除或 legal hold 解除。
- decision diff 只存在 tenant DB 外的 append-only、加密、具 retention 的 evaluation artifact／telemetry store；管理介面為授權唯讀檢視，writer 故障不回寫 tenant DB。
- trace 不含未遮蔽的機密全文、token、密碼或跨租戶資料。

## KQ4：Typed Knowledge 與 Relation Projection

### 目標

把文件、表格、照片、音訊及影片的已核准知識投影成可驗證的型別與關係，仍以 Enclave Knowledge Unit／EvidenceSpan 為唯一來源真相。

### 工作

1. 定義通用 typed kinds：fact、definition、condition、exception、timing、formula、list_member、workflow_step、table_fact、record_field、role_assignment、contact。
2. 修正並驗證 heading chain：清單行不得污染標題階層，每個 EvidenceSpan 保存自身 section path。
3. 建立 stable unit identity：tenant、source revision、EvidenceSpan、content hash 與 projector version 可重現。
4. 建立 relation projection 與 provenance；先支援 condition/exception/member/next_step/same_record。
5. 來源覆核、發布、撤權、tombstone、版本切換與 rollback 必須同步影響 typed projection。
6. 正式 Ask 只能讀取同時滿足 `quality_state=ready`、`KnowledgeUnitRecord.status=active`、`KnowledgeUnitRelease.status=active` 與對應 `membership.status=active` 的 Knowledge Unit；任何條件缺失、未知或不一致一律 fail closed。
7. 上述 admission 後仍須在檢索候選進入 decision 前，以及 claim/citation 核發前，再次通過 tenant／department／source ACL、exact KB／Knowledge Unit revision 與 deny／tombstone 檢查；projection、relation expansion、cache 或 Pack 不得沿用過期授權結果。
8. RetrievalFacade 加入 short value／code exact arm 與 relation expansion，仍經 scope filter。
9. 對音訊／影片保留 speaker、timestamp、keyframe 與 timeline locator。

### 測試矩陣

- heading、list、table、procedure、audio transcript、video timeline。
- stable identity、idempotent reprojection、revision diff。
- relation 不跨 tenant/revision/release。
- `quality_state`、KnowledgeUnitRecord、KnowledgeUnitRelease 或 membership 任一非 ready／active 時，正式 Ask 均不可讀；狀態切換後需驗證 cache/index 立即失效。
- admitted unit 在 ACL/revision/deny 任一二次檢查失敗時不得成為 verified claim 或 citation。
- 清單兄弟完整性、程序下一步、條件／例外 closure。
- revoke/tombstone 後 relation 與 Ask 同步不可用。
- projector failure 不破壞既有 active release。

### Code Review Gate：`KQ-TYPED-01`

- 沒有第二套 source、revision、ACL、release 或 citation authority。
- 正式 Ask 的 ready＋三個 active admission 與 ACL/revision/deny 二次檢查在 sync、stream、relation expansion 與 Pack candidate 路徑一致。
- projection 可全部由 canonical source 重建。
- schema migration 有 fresh、upgrade、downgrade／forward recovery 證據。
- Pack 只能增加 vocabulary／projector，不得寫入其他租戶 relation。

## KQ5：Answer Plan、Renderer 與問答 UX

### 目標

讓正確證據形成直接、完整且可理解的答案，而不是 evidence dump；同時把缺口、衝突與責任呈現在 UI。

### 工作

1. AnswerPlan 支援 scalar、set、procedure、judgment/yes-no、definition、comparison、formula 與 partial gap。
2. 建立 deterministic renderer，作為所有題型的安全 fallback。
3. 新增 constrained paraphrase：只能引用 verified claim IDs，不得新增 facts。
4. SourceVerifier 加入 AnswerPlan claim-ID diff、unsupported entity/numeric/date/scope checks。
5. Enforce 串流採 buffer-until-verified 或 claim-safe staged streaming；不得先吐未驗證事實。
6. Ask UI 顯示：直接結論、適用範圍、來源版本、已回答項目、缺少項目、衝突、需要補充條件與系統錯誤。
7. Evidence drawer 可回到文件頁碼、表格列、圖片區域、音訊／影片時間碼。

### UX 狀態

| EvidenceState | 使用者呈現 | 主要操作 |
|---|---|---|
| complete | 已根據完整證據回答 | 查看引用／回報問題 |
| partial | 已回答可確認部分 | 查看缺少項目／補充資料 |
| insufficient_context | 需要一項必要資訊 | 回答最小澄清問題 |
| absent | 指定範圍未找到依據 | 擴大範圍／新增知識 |
| conflict | 來源存在無法消解差異 | 查看版本與適用範圍／交由人員確認 |
| execution failure | 系統未完成本次判斷 | 重試／使用追蹤碼聯絡管理員 |

### 測試矩陣

- yes/no 必須先直接回答，再列條件。
- comparison 每個比較對象及欄位都完整。
- exhaustive list 必須證明 closed scope 或顯示不完整。
- procedure 保留順序、條件、禁止動作與升級條件。
- 模型新增人名、數字、日期、結論時強制 fallback。
- 桌機、平板、390×844 手機；鍵盤、螢幕閱讀器與無 hover 操作。

### Code Review Gate：`KQ-ANSWER-01`

- AnswerPlan 與自然語言輸出可 deterministic diff。
- renderer failure 不得洩漏未驗證草稿。
- sync/stream 最終 claims、sources、state 完全一致。
- UI 不得把 execution failure 顯示成「公司沒有資料」。

## KQ6：Knowledge Pack 雙領域驗證

### 目標

證明同一核心能服務不同領域，且 Pack 可安裝、停用與移除，不污染核心。

### 工作

1. 擴充 Pack contributions：KnowledgeUnitProjector、RequirementCompiler、EntityAndAliasProvider、ApplicabilityProvider、ResolverProvider、AnswerRenderer、InvariantContribution。
2. 建立小型 HR reference Pack，只放 ontology、lexicon、文件家族、時間規則與 renderer vocabulary，不含優利固定答案。
3. 以製造知識 Pack 建立第二切片：設備型號、程序步驟、參數、異常、工安與正式 SOP applicability。
4. Pack candidate 仍由 core 執行 tenant/ACL/revision/authority 二次驗證。
5. 建立 uninstall/disable negative tests；Pack 移除後 route、provider、projector、resolver、UI 與 permission contributions 一起消失。

### 測試矩陣

- 兩 Pack 不互相 import。
- 未安裝 Pack 時 core contract tests 全通過。
- HR corpus 不出現製造 facets；製造 corpus 不出現 HR 預設。
- tenant alias 不跨租戶共享。
- Pack failure 回傳 execution status，不轉成 absent。
- 高風險製造題只允許正式核准權威或 escalate。

### Code Review Gate：`KQ-PACK-01`

- core contamination scan 為 0。
- Pack 卸載乾淨且 fail closed。
- 同一 EvidenceDecision schema 同時處理兩領域。
- 沒有 Pack 直連 DB／index 繞過 platform contract。

## KQ7：Sealed Evaluation、受控 Enforce 與正式發布

### 目標

以可重現的技術測試證明跨領域能力，並以 feature flag、allowlist、kill switch 與 rollback 控制逐租戶啟用。

### 工作

1. 建立六階段 invariants：parse、retrieve、select、applicability、completeness、conversation。
2. AIHR 已知案例只轉成 regression/neighbor tests，標記來源與揭露狀態。
3. 提供可選用的 holdout 工具；其執行者與書面 attestation 不列入開發完成條件。
4. 提供 200 題／四領域／混合語言的 QA profile 作為選用 benchmark，不作 release blocker。
5. 另建高風險無答案／錯誤前提集合，量 false acceptance。
6. 以 deployment mode、tenant allowlist 與 kill switch 控制 `off → shadow → enforce`；不要求客戶書面簽核。
7. Signed authorization 保留為選用 governance integration，預設關閉，不阻擋 shadow 或 enforce。
8. 所有 tenant 使用相同技術控制，不加入客戶名稱特判。
9. 綁定 backend/frontend image、deployment manifest、KB revision、Knowledge release、Pack versions、prompt/model 與 rollback point。
10. 完成回滾演練及 enforce kill switch。

### 選用 QA Benchmark（不阻擋開發或發布）

- Internal alpha：strict pass ≥85%，各領域 ≥80%，critical error 0。
- External beta：strict pass ≥90%，各領域 ≥85%，critical error 0。
- GA：strict pass ≥95%，各領域 ≥90%，critical error 0。
- false acceptance、false rejection、partial correctness、conflict correctness 必須分開報告，不得只給總分。
- Provider/schema/timeout/pack failure 不納入安全拒答分子。
- Tenant acceptance 每租戶 30–50 題起，另含 ACL、revision、無答案、多輪與瀏覽器流程；不計入平台 sealed 分數。

### Code Review Gate：`KQ-RELEASE-01`

- 正式 Shadow mutation 0，sync/stream parity 通過。
- rollback 能恢復舊 decision path 與既有 Ask SLA。
- 獨立瀏覽器驗收與 operator evidence 完成後才可 enforce。

## 7. 跨階段測試與品質策略

### 7.1 固定題型矩陣

每一個 phase 至少覆蓋：

- scalar／單一事實
- set／完整清單
- procedure／條件分支
- judgment／yes-no
- definition
- comparison
- formula／deterministic aggregate
- partial evidence
- absent evidence
- insufficient context
- true conflict／false conflict
- wrong entity／wrong scope／wrong revision
- revoked／expired／tombstoned source
- provider／schema／timeout／pack failure
- multi-turn carry、topic switch、correction

### 7.2 六階段失敗歸因

| Stage | 必測問題 |
|---|---|
| Parse | 問題需求與原始 token 是否完整保留？ |
| Retrieve | 正確證據是否在候選中，scope 是否正確？ |
| Select | 真正回答本題的證據是否保留，相鄰主題是否排除？ |
| Applicability | tenant/entity/version/authority/time 是否適用？ |
| Completeness | facets、branches、cardinality 與 closed list 是否完整？ |
| Conversation | 多輪條件是否承接、修正、換題且不重問？ |

已知問題使用 strict expected-failure registry；修復後 XPASS 必須促使移除或更新紀錄，禁止問題無聲消失。

### 7.3 測試層級

1. Contract/unit：純 deterministic，不呼叫外部模型。
2. PostgreSQL integration：真實 RLS、revision、relation、transaction 與 migration。
3. Provider contract：schema、timeout、空回答、重試與成本。
4. Regression：AIHR 已揭露案例與 Enclave 已知事故。
5. Shadow：正式資料唯讀比較，不改使用者回答。
6. Sealed：未見 corpus＋未見問題，首次結果不可覆寫。
7. Browser acceptance：真實 UI、來源卡、狀態、手機與權限。

## 8. 可觀測性與營運指標

### 8.1 品質

- requirement parse accuracy。
- recall@K 與 scope recall。
- evidence admission precision／recall。
- complete、partial、clarify、abstain、conflict 分類正確率。
- false acceptance 與 false rejection。
- required facet／branch／cardinality completeness。
- unsupported claim、unsupported numeric/entity/date rate。
- citation exactness 與 source accessibility。

### 8.2 效能與成本

- parse、retrieve、select、decision、render、verify 分階段 P50/P95/P99。
- off／shadow／enforce 的完整回答延遲差異。
- cost per query、cost per verified answer、shadow cost。
- relation expansion candidate count 與上限截斷率。
- provider fallback、timeout、retry 與 deterministic fallback rate。

### 8.3 產品結果

- 使用者追問率與澄清完成率。
- 部分回答後成功補齊率。
- 引用開啟率與錯誤來源回報率。
- 知識缺口建立、補充、發布與關閉週期。
- conflict/escalation 的處理時間。

## 9. 安全、權限與資料生命週期

- 所有 typed units、relations、requirements、decisions、traces 必須 tenant-scoped。
- Pack、shadow 與 eval candidate 仍需經 core ACL/revision/deny checks。
- EvidenceDecision 不得保存使用者無權查看的 quote；UI 重新讀取來源時再次授權。
- 來源撤權、tombstone、retention expiry、legal hold 與 KB rollback 必須有對應 decision/index invalidation。
- Shadow 預設只保存 hash、IDs、reason codes 與必要片段；完整內容另受限權限與保存期。
- KQ3 decision diff 的持久化只允許 tenant DB 外的 append-only、加密 evaluation artifact／telemetry store；retention expiry／legal hold／purge audit 與管理端重新授權讀取均為資料生命週期契約。
- 高風險安全、工安、法律、財務與品質放行題必須有較高 authority requirement；不足時 escalate，不允許模型自行補足。
- ExecutionStatus 與 trace 不得暴露 API key、token、內部 prompt、跨租戶 metadata 或原始錯誤堆疊給一般使用者。

## 10. Feature Flags 與回滾

最低旗標：

```text
KNOWLEDGE_DECISION_MODE=off|shadow|enforce
KNOWLEDGE_DECISION_TENANT_ALLOWLIST=
KNOWLEDGE_TYPED_PROJECTION_ENABLED=false
KNOWLEDGE_RELATION_EXPANSION_ENABLED=false
KNOWLEDGE_ANSWER_PLAN_ENABLED=false
KNOWLEDGE_CONSTRAINED_PARAPHRASE_ENABLED=false
```

規則：

- 預設全部 off。
- Flag 解析失敗採 off，並記錄 execution/config error。
- Enforce 只能對 allowlist tenant 啟用。
- allowlist 不是授權證明；enforce 還必須通過 KQ7 的 tenant-specific Owner approval 檢查，缺失、過期或 scope 不符時採 off。
- 回滾不得要求重建既有 active index；切回 legacy path 後既有 Ask 必須可用。
- Schema migration 先 expand，再 dual-read/shadow，最後才 contract；本計畫內不立即刪 legacy 欄位。

## 11. 每階段 Code Review 標準流程

每個 phase 建立獨立 `PHASE_KQx_CODE_REVIEW_YYYY-MM-DD.md`，至少回答：

1. 本 phase 改變哪個 canonical owner？
2. 是否新增平行 aggregate、retrieval、revision、citation 或 decision？
3. tenant/department/source ACL、RLS、KB revision 與 deny-set 是否完整？
4. sync、stream、background、shadow 是否使用同一契約？
5. provider failure 是否可能被誤算為 absent／abstain？
6. false rejection 與 false acceptance 是否都有測量？
7. migration、backfill、reprojection 是否 idempotent 且可恢復？
8. Pack 停用／故障／移除是否 fail closed？
9. trace、metrics 與 UI 是否洩漏機密或跨租戶 metadata？
10. 既有 Input、Ask、citation、delete/revoke 與 release rollback 是否回歸？
11. 是否有明確 rollback 指令與停止條件？
12. 測試證據是否綁定 exact source commit、image、schema、KB revision 與 Pack versions？
13. Shadow diff 是否只寫入 tenant DB 外的 append-only 加密 store，且 retention、legal hold、purge audit 與管理端再授權完整？
14. 進入 enforce 的 tenant 是否命中 allowlist，且 kill switch 與 rollback 可用？

Review 結論只能是：

- `PASS TO NEXT PHASE`
- `PASS FOR SHADOW`
- `PASS FOR CONTROLLED ENFORCE`
- `BLOCKED`

不得使用模糊的「大致完成」。

## 12. 初始 Backlog 與依賴

| ID | Phase | 工作 | 主要位置 | 依賴 |
|---|---|---|---|---|
| KQ-001 | KQ0 | 凍結 Live Ask sync/stream baseline | `chat_orchestrator.py`、API tests、`artifacts/knowledge` | 無 |
| KQ-002 | KQ0 | AIHR→Enclave schema mapping ADR | `docs/adr` | KQ-001 |
| KQ-003 | KQ0 | 決策呼叫圖與 legacy owner 盤點 | services/gateway | KQ-001 |
| KQ-004 | KQ0 | core contamination scanner 規則擴充 | scripts/tests | KQ-002 |
| KQ-101 | KQ1 | 三狀態 enum/schema | evidence contracts | KQ-BL-01 |
| KQ-102 | KQ1 | AnswerRequirement 與具名 gap | `evidence_contract.py` | KQ-101 |
| KQ-103 | KQ1 | full field validation | `evidence_contract.py` | KQ-102 |
| KQ-104 | KQ1 | legacy adapter | `retrieval_coverage.py` | KQ-101 |
| KQ-201 | KQ2 | single EvidenceDecision API | `evidence_orchestrator.py` | KQ-CONTRACT-01 |
| KQ-202 | KQ2 | applicability/authority/temporal pipeline | services | KQ-201 |
| KQ-203 | KQ2 | cardinality/relation/conflict engine | services | KQ-201 |
| KQ-204 | KQ2 | six-stage trace | services/eval | KQ-201 |
| KQ-301 | KQ3 | off/shadow/enforce flags | config/runtime | KQ-DECISION-01 |
| KQ-302 | KQ3 | read-only shadow adapter | Ask/runtime | KQ-301 |
| KQ-303 | KQ3 | tenant DB 外 append-only decision diff store、metrics 與授權唯讀 UI | evaluation telemetry/API/frontend | KQ-302 |
| KQ-401 | KQ4 | typed payload/heading lineage | ingestion/knowledge unit | KQ-SHADOW-01 |
| KQ-402 | KQ4 | relation ADR/model/projection | models/services | KQ-401 |
| KQ-403 | KQ4 | exact/short-value/relation retrieval | RetrievalFacade | KQ-402 |
| KQ-404 | KQ4 | revoke/version/reprojection lifecycle | services/tasks | KQ-402 |
| KQ-501 | KQ5 | AnswerPlan schema/renderer | services | KQ-TYPED-01 |
| KQ-502 | KQ5 | constrained paraphrase/claim diff | renderer/verifier | KQ-501 |
| KQ-503 | KQ5 | Ask decision/evidence UX | frontend | KQ-501 |
| KQ-601 | KQ6 | Pack contract contributions | `app/platform/packs` | KQ-ANSWER-01 |
| KQ-602 | KQ6 | HR reference Pack | packs | KQ-601 |
| KQ-603 | KQ6 | manufacturing Pack slice | packs | KQ-601 |
| KQ-701 | KQ7 | AIHR regression import manifest | tests/eval | KQ-PACK-01 |
| KQ-702 | KQ7 | new sealed holdout workflow | eval/artifacts | KQ-701 |
| KQ-703 | KQ7 | controlled enforce/rollback drill | deployment/runtime | KQ-702、既有技術 gates |

## 13. 依賴順序與可並行項目

不可顛倒：

```text
KQ0 → KQ1 → KQ2 → KQ3 → KQ4 → KQ5 → KQ6 → KQ7
```

可在不改變 phase gate 的情況下並行：

- KQ0 baseline cases 與 mapping ADR。
- KQ1 schema tests 與 legacy adapter。
- KQ3 metrics backend 與管理 UI prototype。
- KQ4 heading lineage 與 relation schema prototype。
- KQ5 deterministic renderer 與 evidence drawer prototype。
- KQ7 額外 holdout 可由 QA 平行準備，但不阻擋開發完成或發布。

不提供固定日曆工期；KQ0 完成前，dirty worktree、既有未合併能力與正式 Ask 基線尚未形成可負責任估算。KQ0 Code Review 必須產生各 phase 的 S/M/L effort、關鍵路徑與風險緩衝。

## 14. 停止條件

遇到以下任一條件立即停止推進，不得用調低門檻掩蓋：

- 無法重現 KQ0 baseline。
- 新 decision 出現跨租戶、錯 revision、撤權後仍可回答或來源不可存取。
- provider/schema failure 被記為 absent 或安全拒答。
- Shadow 對正式 tenant 產生資料 mutation。
- false rejection/acceptance 無法分開計算。
- sync 與 stream 最終 decision／claims／citations 不一致。
- Pack 可繞過 RetrievalFacade、ACL、KB revision 或 SourceVerifier。
- renderer 產生 AnswerPlan 以外的新公司事實。
- 既有 Input I9、刪除撤權、Owner review 或 Ask 引用回歸。
- migration/backfill 無法安全回復。

## 15. 完成定義

本計畫只有在以下條件全部成立時才算完成：

1. Live Ask sync/stream 只消費一個 canonical EvidenceDecision。
2. EvidenceState、ResponseAction、ExecutionStatus 三者資料、UI、metrics 與 eval 分離。
3. required facets、scope、entity、revision、authority、temporal、cardinality、relation closure 均由伺服器驗證。
4. complete、partial、clarify、abstain、conflict、execution failure 均有可理解 UI 與下一步。
5. 每個輸出 claim 可回到可存取的 exact source revision/EvidenceSpan。
6. 模型無法新增 AnswerPlan 外的人名、數字、日期、條件、範圍與結論。
7. HR 與製造 Pack 使用同一核心，彼此無 import，停用後乾淨 fail closed。
8. 已揭露案例只作 regression；技術測試 critical error 0。
9. 正式 Shadow mutation 0，受控 enforce 可一鍵回舊版。
10. 每個 KQ phase 均有 Code Review、測試證據、部署／不部署決策與回滾記錄。

## 16. 已完成的第一個工作包（歷史）

本計畫核准後先執行 KQ0，當時未直接修改 Live Ask：

1. 建立目前 sync/stream Ask 呼叫圖。
2. 凍結 12 類代表問題及完整回答／sources／trace。
3. 建立 AIHR type/relation/service → Enclave owner mapping ADR。
4. 建立 `retrieval_coverage` 與 `EvidenceOrchestrator` decision divergence 清單。
5. 建立 core contamination scan 與 known-failure registry。
6. 完成 `KQ-BL-01` Code Review 後，回報 KQ1 精確修改檔案、migration 判斷、測試數與 effort。

KQ0 執行期間未改正式回答、未部署新 decision，也未干擾李永仁第二輪 Input 測試；後續 KQ1–KQ7 已依序完成。

## 17. 最終產品意義

Input I9 解決的是「各種企業內容能否可靠進來並被治理」。本計畫解決的是「內容進來後，系統能否對每個問題做出可驗證的回答決定」。兩者合併後，Enclave 的核心產品主張才完整：

```text
可靠匯入多元來源
  → 建立可追溯、可版本化、可授權的知識
  → 判斷證據是否適用、完整、衝突或不足
  → 只輸出可被證據支持的直接答案
  → 讓領域差異由可拆裝 Pack 擴充
```

成功不等於 Enclave 能重跑 AIHR 的 61 題；成功是同一份 Enclave Kernel 在不加入客戶題目特判的前提下，能讓不同租戶及不同 Pack 對完整、部分、缺條件、無答案與衝突做出可追蹤、可回滾、可由使用者理解的正確處理。

## 18. 版本紀錄

| 版本 | 日期 | 摘要 |
|---|---|---|
| 1.0 | 2026-09-03 | 建立 KQ0–KQ7 Live Ask EvidenceDecision 收斂增量計畫。 |
| 1.1 | 2026-09-03 | 完成第一次文件複查必要修訂：指定 tenant DB 外 append-only／加密／retention Shadow diff store 與管理端讀取邊界；凍結 KQ-SHADOW-01 真實案例與首跑門檻；補正式 Ask ready/active admission 與 ACL/revision/deny 二次檢查；建立 tenant Owner shadow/enforce 二階段授權且八策不自動授權；baseline JSON 移至 `artifacts/knowledge`；釐清 Shadow 關閉後的請求成本與 retention 儲存。 |
| 1.2 | 2026-09-03 | 依 Owner 指示，將獨立陌生題盲測與客戶書面簽核移出開發及發布阻斷條件；保留為選用 QA／治理工具。Technical rollout 改由 mode、allowlist、kill switch、release identity 與 rollback 控制。 |
