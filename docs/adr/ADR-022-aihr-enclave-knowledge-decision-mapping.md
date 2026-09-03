# ADR-022：AIHR 能力映射至 Enclave Knowledge Decision

- 狀態：Accepted for KQ0 mapping；runtime implementation deferred to KQ1–KQ7
- 日期：2026-09-03
- 決策範圍：Knowledge Answer Reliability KQ0
- 依據：ADR-014、ADR-018、ADR-020、`EXISTING_CAPABILITY_DISPOSITION.md`

## 背景

AIHR 已提供 typed evidence、relation expansion、server-owned sufficiency、deterministic assembly 與六階段 invariant 的實證，但其 `hr_pv_t0_*` 同時綁定 HR 文件家族、客戶語料、題目與專用規則。Enclave 已有多租戶 canonical assets、EvidenceSpan、Knowledge Unit revision/release、RetrievalFacade、QuerySpec 骨架、EvidenceContract、SourceVerifier、Pack runtime 與 sealed/shadow gate。若直接搬移 AIHR graph 或 service，會建立第二套 source、revision、retrieval、decision 與 citation authority。

KQ0 的責任是決定每項能力的 canonical owner，並以現行程式呼叫圖證明真正差距；本 ADR 不改 Live Ask 行為。

## 決策

### 1. 唯一主幹

- `AssetRevision`／`DerivedArtifact`／`EvidenceSpan`／`KnowledgeUnitRecord`／`KnowledgeUnitRevision`／`KnowledgeUnitRelease` 繼續是唯一知識與版本權威。
- `RetrievalFacade` 繼續是唯一檢索主幹。任何 typed candidate、relation expansion 或 Pack provider 都必須回到 Facade，並再次通過 tenant、ACL、exact revision、release membership 與 deny/tombstone。
- `CitationBuilder`／EvidenceSpan locator 繼續是唯一 citation authority。
- `EvidenceOrchestrator` 在 KQ2 擴充後成為唯一 pre-generation `EvidenceDecision` owner；KQ0 與 KQ1 不接管 Live Ask。
- `retrieval_coverage.assess_retrieval_coverage()` 在 KQ1 只可包裝成 compatibility adapter，在 KQ3 只可作 shadow comparator；完成 parity 後不得再擁有正式答案放行權。
- `SourceVerifier` 保留為回答後 defense in depth，不得成為完整性或缺席的唯一判定者。

### 2. Typed payload 處置

AIHR `TypedAtom` 不形成新 aggregate。KQ4 先把 domain-neutral typed payload 放在 immutable `KnowledgeUnitRevision.metadata_json["typed_payload"]`，並以 schema version 驗證：

```text
kind, subject, predicate, value, value_type, statement
conditions[], exceptions[], applies_to[], topic_tags[]
entity_ids[], authority_class, effective_range, risk_class
source_span_id, exact_quote, section_path, content_hash
```

若實作量測證明 JSON 無法滿足查詢索引或 migration 安全，才可提出欄位正規化 amendment；不得建立第二套 Knowledge Unit 或 content revision。

### 3. Relation 儲存決策

現有 repository 沒有 revision-to-revision relation model，也沒有可用外鍵約束的等價結構。只把 relation 放入 JSON 無法可靠保證：

- source/target 同 tenant；
- target revision 真實存在且沒有跨 release；
- revoke、tombstone、release 切換與 rollback 後同步失效；
- `condition_of`、`exception_of`、`member_of`、`next_step`、`same_record` 的雙向索引與 closure 上限；
- provenance、review state 與 projector version 可稽核。

因此 KQ4 可以新增 **`KnowledgeUnitRelationProjection`** revision-scoped projection table，但它不是第二套 graph authority：

- source 與 target 必須以 `(tenant_id, knowledge_unit_revision_id)` composite FK 指向既有 `KnowledgeUnitRevision`；
- relation 沒有獨立 content、ACL、revision lifecycle 或 release；可見性完全繼承兩端 active release membership，且任一端失效即不可讀；
- 只能由 canonical EvidenceSpan／KnowledgeUnitRevision 重新投影，保存 projector/schema version、provenance 與 content hash；
- 不提供繞過 RetrievalFacade 的查詢 API；relation expansion 只回傳 candidate IDs，再由 core admission 重驗；
- KQ4 migration 必須提供 fresh、upgrade、downgrade／forward recovery、idempotent reprojection 與 tenant isolation 證據。

### 4. Pack 邊界

AIHR 的 HR ontology、文件家族、alias、時間級距與 renderer vocabulary 只能進 Knowledge／Domain Pack。KQ6 可擴充標準 contribution：`KnowledgeUnitProjector`、`RequirementCompiler`、`EntityAndAliasProvider`、`ApplicabilityProvider`、`ResolverProvider`、`AnswerRenderer`、`InvariantContribution`。Pack 不得直接查 tenant DB/index、核發 final decision 或自建 citation。

### 5. 評測與產物

- AIHR 61 題、real-*、Z3/Z4 與已揭露問題只能是 regression／neighbor evidence，不得進新 sealed holdout。
- KQ0 baseline JSON、call graph、API schema、outputs、known failures 與 contamination scan 一律置於 `artifacts/knowledge/`；`docs/` 只保存說明與相對 reference。
- KQ3 decision diff 依 Task Plan v1.1 寫入 tenant DB 外的 append-only、加密、具 retention 的 evaluation artifact／telemetry store；這不是 Knowledge Unit 或 conversation authority。

## AIHR → Enclave owner mapping

| AIHR 能力 | Enclave canonical owner | 處置 | 階段 |
|---|---|---|---|
| FactBundleChunker heading chain | document parser／EvidenceSpan lineage | 擴充，不搬 HR 文件規則 | KQ4 |
| TypedAtom | KnowledgeUnitRevision typed payload | 擴充 JSON projection，不建 atom aggregate | KQ4 |
| AtomRelation | KnowledgeUnitRelationProjection | 新增可重建 projection table；無獨立 authority | KQ4 |
| DocumentApplicability | KnowledgeUnitRevision applicability＋AuthorityPolicy＋release | 擴充，不建平行 document truth | KQ2/KQ4 |
| EntityRegistry | tenant-scoped entity/alias service | 擴充；客戶 alias 不全域共享 | KQ4/KQ6 |
| RequirementSlot／asked facets | QuerySpec＋AnswerRequirement/EvidenceContract | 擴充通用契約 | KQ1 |
| retrieve_candidates | RetrievalFacade | 擴充 exact/short/relation arms | KQ4 |
| Rule A／topic partition | Evidence admission＋Pack vocabulary | 重寫為通用 validator，先 shadow | KQ2/KQ3 |
| document precedence | AuthorityPolicy＋applicability | 擴充情境矩陣 | KQ2 |
| compute_state／unanswered facets | EvidenceOrchestrator | 收斂為唯一 EvidenceDecision | KQ2 |
| temporal resolver | generic resolver＋Pack rule | 通用計算在 core，領域級距在 Pack | KQ2/KQ6 |
| PV-T0 renderer | AnswerPlan＋deterministic renderer | 重建通用輸出契約，不搬固定答案 | KQ5 |
| six-stage invariants | platform eval runtime＋Pack tests | 擴充 sealed/shadow schema | KQ7 |

## 後果

- KQ1–KQ7 必須沿本 ADR 擴充既有 owner；若新增 aggregate，Code Review 必須先證明本 ADR 的 owner 無法承接並補 amendment。
- `KnowledgeUnitRelationProjection` 是本次唯一預先核准的新增 persistence 類型，但只能在 KQ4、通過 KQ3 Review 後施工。
- 目前 Live Ask 的實際 final decision 仍是 `retrieval_coverage`；此差距已凍結於 `artifacts/knowledge/KQ_CALL_GRAPH.json` 與 `KQ_KNOWN_FAILURES.json`，不可在 KQ0 偷改行為。
- 本 ADR 不解除 `KQ-BL-01`；新鮮正式唯讀 release identity 未取得前不得開始 KQ1。
