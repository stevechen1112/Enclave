# Phase KQ2 Code Review — 2026-09-03

結論：`PASS TO NEXT PHASE`
Gate：`KQ-DECISION-01`
範圍：離線／測試用 canonical EvidenceDecision engine；未接 Live Ask、未部署

## 結果

既有 `EvidenceOrchestrator.decide_evidence` 已升級為唯一 `EvidenceDecision` schema owner。流程依序執行 contract admission、ACL/revision/deny/tombstone/release/quality recheck、applicability/authority/time、relation/cardinality/completeness、same-scope conflict 及 deterministic derivation。相鄰證據只進 `near_evidence`，不會成為 `verified_claims`。

Decision 包含 query/contract version、三個正交狀態、具名 gaps/conflicts、reviewed scope、KB/Knowledge release、Pack versions、六階段 trace、trace ID 與 deterministic decision hash；evidence serialization 只暴露 source refs 與 value hash，不含 quote/value。

## Review checklist

1. Canonical owner：repository 只有 `evidence_orchestrator.EvidenceDecision` 定義最終新版 decision；legacy coverage 只保留相容輸入／比較。
2. 平行 aggregate/retrieval/revision/citation：無。
3. ACL/RLS/revision/deny：item 在 claim admission 前檢查 ACL、active revision、deny、tombstone、release active 與 quality ready；DB/RLS 仍由 RetrievalFacade owner。
4. Sync/stream/background/shadow：KQ2 尚未接線，KQ3 才由共用 adapter 呼叫。
5. Provider failure：execution failure 會清空 verified claims 並 escalate，不會算 absent。
6. False acceptance/rejection：complete/partial/absent/clarify、真／假 conflict、near evidence 與 admission 正反例皆測。
7. Migration：無。
8. Pack failure：沿用 ExecutionStatus.PACK_FAILURE，Pack versions 納入 hash。
9. Privacy：trace 只保存計數、reason code、hash 與 refs。
10. Regression：KQ2/KQ1/Knowledge engine/QueryPlan 共 70 passed。
11. Rollback：revert KQ2 commit；正式 Ask 尚未使用此 engine。
12. Evidence binding：decision 可綁 exact KB revision、Knowledge release、Pack versions。
13. Shadow store：未建立，留給 KQ3。
14. Enforce authorization：不適用。

## 驗證

- KQ2 專用：8 passed；涵蓋五種 evidence state/action 路徑、ACL/revision/deny、真／假 conflict、時間不重疊、aggregate registry、execution failure、六 stage trace 與 deterministic replay。
- 相關回歸：70 passed。
- Core contamination：271 files，0 unwaived findings。
- `compileall`、`git diff --check`：PASS。

## Review 決定

`PASS TO NEXT PHASE`

允許進入 KQ3 Live Ask shadow；預設必須 off，且不得改變使用者答案或寫 tenant operational DB。
