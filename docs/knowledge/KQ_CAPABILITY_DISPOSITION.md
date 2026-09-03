# KQ0 Knowledge Answer Capability Disposition

日期：2026-09-03
狀態：KQ0 mapping complete；runtime changes not started
依據：`ADR-022-aihr-enclave-knowledge-decision-mapping.md`

本文件只補充 Knowledge Answer Reliability 的 Live Ask 決策責任；不取代 `EXISTING_CAPABILITY_DISPOSITION.md`。未列為 `new projection` 的能力不得新增平行模型或服務。

| 能力 | 現行 owner／真實呼叫 | KQ 處置 | 禁止事項 | 完成／退場條件 |
|---|---|---|---|---|
| Live Ask sync endpoint | `app/api/v1/endpoints/chat.py::chat` | 沿用 | 新增第二個 Ask API | 與 stream 共用 QuerySpec、EvidenceDecision、AnswerPlan |
| Live Ask stream endpoint | `app/api/v1/endpoints/chat.py::chat_stream` | 沿用 | 未驗證 claim 先串流 | 與 sync 最終 claims/state/citations parity |
| 多輪改寫 | `ChatOrchestrator.contextualize_query` | 擴充 preservation／ambiguity | 用改寫遺失原 token | correction/topic switch/known-input invariants 通過 |
| 問題規劃 | `query_plan.build_query_plan` | 擴充為版本化 QuerySpec parser | 平行 query router；題目特判 | KQ1 contract 與 preservation gate |
| 多步編排 | `MultiStepOrchestrator` | 沿用 | Pack 自建旁路 orchestration | 所有 arm 經同一 trace/scope |
| 檢索 | `RetrievalFacade` | 擴充 exact、short-value、relation candidate | Pack 直查 DB/index | 所有 candidate 重驗 ACL/revision/deny |
| Legacy coverage | `retrieval_coverage.assess_retrieval_coverage`，目前 Live Ask final decision | adapter → comparator → 退場 | 與新 engine 各自核發正式答案 | KQ3 parity 後移除 final authority |
| Answer requirement | `EvidenceContract`／`AnswerSlot` | 擴充欄位與實際 validation | Pack 自行放行 required facet | KQ1 具名 gap 與正負例通過 |
| 最終 pre-generation decision | `EvidenceOrchestrator`，目前只被 tests 呼叫 | 擴充為唯一 owner | 第二個 decision aggregate | KQ2 repository 只有一個 owner |
| 回答後驗證 | `SourceVerifier` | 沿用 defense in depth | 用 verifier 代替 pre-generation completeness | claim-ID diff 與 sync/stream parity |
| Canonical knowledge identity | `KnowledgeUnitRecord` | 沿用 | TypedAtom 第二主表 | stable unit identity 可重建 |
| Canonical immutable content | `KnowledgeUnitRevision` | 擴充 `metadata_json.typed_payload` | 第二套 atom revision | schema-versioned typed projection |
| Knowledge release | `KnowledgeUnitRelease`＋membership | 沿用 | relation/Pack 自建 release | ready＋record/release/membership active admission |
| Relation | repository 尚無等價 owner | **new projection**：`KnowledgeUnitRelationProjection` | 獨立 graph truth、ACL、revision、release、query API | composite FK、可重建、只經 Facade、KQ4 migration/recovery |
| 適用性 | KnowledgeUnit applicability＋`AuthorityPolicy` | 擴充 | 固定 ranking 隱藏 scope 差異 | 同事項同 scope/time 才能 conflict |
| Citation | `CitationBuilder`／EvidenceSpan locator | 沿用 | renderer/Pack 自造 citation | exact revision/source access 可重驗 |
| Structured record | `StructuredRecordResolver` | 沿用／擴充 | 回到 `structured_answers.py` 新增規則 | row identity/cardinality deterministic |
| Procedure | `ProcedureResolver` | 沿用／擴充 | LLM 自選分支 | branch/condition/exception closure |
| HR compatibility | feature-flagged `app/knowledge_packs/hr_compatibility.py`；legacy `structured_answers.py` | 遷移後退場 | 新增 HR/client branch 到 core | generic resolver parity＋Pack tests＋移除 direct path |
| Pack runtime | `app/platform/packs/contracts.py`／registry | 擴充標準 knowledge contributions | Pack 直連 DB/index/decision | uninstall/disable fail-closed tests |
| Shadow/eval | 既有 sealed/shadow runtime | 擴充 KQ 六階段與 out-of-band diff artifact | tenant DB 記錄 diff；覆寫 first-run | KQ3/KQ7 gates |
| UX | Ask UI／evidence drawer | 擴充 decision/gap/conflict/execution states | 單一「不知道」掩蓋原因 | KQ5 browser acceptance |

## 唯一新增 persistence 判定

KQ0 僅核准 KQ4 可提出 `KnowledgeUnitRelationProjection` migration；理由與限制見 ADR-022。它只能是既有 `KnowledgeUnitRevision` 的 revision-scoped、可重建 projection，不得成為 source、content、ACL、release、retrieval 或 citation authority。

其餘 AIHR type/service 一律為 `reuse`、`extend`、`adapter`、`pack` 或 `reject`；不得複製 `hr_pv_t0_*`。

## 現行呼叫真相

機器可讀呼叫圖：`../../artifacts/knowledge/KQ_CALL_GRAPH.json`。目前 Live Ask 使用 `retrieval_coverage`，`EvidenceOrchestrator` 只在測試引用；這是 KQ2 要收斂的已知差距，不是 KQ0 可直接修正的項目。
