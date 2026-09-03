# KQ6 Code Review — Domain Pack Extension Contract

- 日期：2026-09-03
- Gate：`KQ-PACK-01`
- 結論：**PASS TO NEXT PHASE**

## Review 結論

KQ6 沿用既有 Pack registry 與 canonical `EvidenceDecision`，沒有建立第二套檢索、revision、authority 或 citation 流程。新增的知識 Pack contract 僅允許七種 pure contribution：projector、requirement compiler、entity/alias provider、applicability provider、resolver provider、answer renderer vocabulary 與 invariant contribution。

Pack 只能交付包含 tenant、unit revision、source revision、artifact 與 evidence span 的候選引用，不能提交 final answer。核心會重新驗證 tenant、ACL、active revision、release、quality、denied/tombstone 與 authority；高風險製造候選只接受正式核准 SOP／primary authority。Provider 例外會回傳 `pack_failure` 並升級，不會偽裝成 absent。

HR reference Pack 只含 ontology、lexicon、document family、temporal/applicability rules 與 renderer vocabulary，沒有 customer-fixed answers。Manufacturing reference slice 包含 equipment model、procedure step、process parameter、anomaly、safety constraint 及正式 SOP applicability。兩個 Pack 互不 import，也沒有 SQLAlchemy、model、DB、index 或 retrieval bypass import。

Runtime 使用 tenant-scoped immutable snapshots；disable/uninstall 會原子移除該 Pack 的全部七種貢獻與 version binding。未啟用 tenant 無法取得其他 tenant 的 alias contribution。

## 驗證證據

- KQ0–KQ6 與既有 Pack runtime：114 passed，0 failed。
- Ruff（KQ6 新增核心、兩個 Pack、測試）：PASS。
- Core contamination scan：0 findings。
- Pack direct DB/index bypass scan：0 findings。
- Machine-readable report：`artifacts/knowledge/KQ6_GATE_REPORT.json`。

## Gate 判定

兩個 domain 使用相同 core contract 與 `EvidenceDecision` schema；無 Pack 時核心仍可獨立運作；disable、uninstall、failure、跨 tenant 與高風險負例全部 fail closed。`KQ-PACK-01` 通過，允許開始 KQ7；正式 `KNOWLEDGE_DECISION_MODE` 仍為 `off`。
