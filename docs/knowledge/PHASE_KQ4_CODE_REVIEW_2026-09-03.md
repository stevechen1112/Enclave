# KQ4 Code Review — Typed Knowledge 與 Relation Projection

- 日期：2026-09-03
- Gate：`KQ-TYPED-01`
- 結論：**PASS TO NEXT PHASE**

## Review 結論

KQ4 沿用 `KnowledgeUnitRecord`、immutable `KnowledgeUnitRevision`、`KnowledgeUnitRelease`、membership、`SourceAsset`、`DerivedArtifact` 與 `EvidenceSpan` 作為唯一 authority。唯一新增的 persistence 是 `KnowledgeUnitRelationProjection`；它沒有自己的 content、ACL、revision、release 或 lifecycle，僅保存 revision-to-revision 的可重建 edge、content hash、projector version 與 provenance。

正式讀取仍只由 `RetrievalFacade` 進入 canonical authority。Admission 同時要求 unit active、revision ready、release active、membership active，並在候選使用前重新驗證 tenant/source ACL、精確 asset revision、ready artifact、EvidenceSpan lineage 與 tombstone。Relation expansion 會再次驗證兩端 admission、同一 active release 與 content hash，不直接核發答案或 citation。

## 實作核對

- 12 種 domain-neutral typed kinds 已由 `KnowledgeUnitRevision.metadata_json["typed_payload"]` 承載，沒有建立第二套 atom aggregate。
- DOCX Heading 1–6 與 Markdown heading 保存完整 section path；清單行不修改 heading chain。
- Stable identity 綁定 tenant、source revision、EvidenceSpan、kind、content hash 與 projector version。
- condition、exception、member、next_step、same_record edge 使用 tenant-scoped composite revision FK。
- Projection batch 使用 savepoint 保證 projector failure 不替換既有 active release。
- Short value/code exact ranking 與 relation expansion 都在既有 `RetrievalFacade` 內，沒有第二個 retriever。
- 文件、表格、音訊與影片 locator 保留 section、row/cell、speaker、timestamp 與 frame 資訊。
- 正式 decision mode 維持 `off`，未改動 Input I9 路徑。

## 驗證證據

- Focused contract／authority／asset／retrieval／gateway：87 passed，0 failed。
- Ruff：PASS。
- 隔離 PostgreSQL 16：upgrade、downgrade、forward recovery、`section_path`、FORCE RLS、tenant policy 全部 PASS。
- Migration 重現工具：`scripts/knowledge_kq4_migration_gate.py`。
- Machine-readable report：`artifacts/knowledge/KQ4_GATE_REPORT.json`。

## Gate 判定

`KQ-TYPED-01` 的四項條件全部成立：沒有第二套 authority、所有讀取分支採同一 fail-closed admission、projection 可由 canonical source 重建、migration recovery 與 tenant isolation 已有 PostgreSQL 證據。允許開始 KQ5；本結論不構成 KQ7 Enforce 授權。
