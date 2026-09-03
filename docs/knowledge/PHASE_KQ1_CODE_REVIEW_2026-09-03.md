# Phase KQ1 Code Review — 2026-09-03

結論：`PASS TO NEXT PHASE`
Gate：`KQ-CONTRACT-01`
範圍：通用契約與 legacy adapter；未接管 Live Ask、未部署

## 結果

KQ1 將 QuerySpec 升為 2.0，新增 deterministic query ID、原始問題、requirement shape、facets、source scope 與 preservation validation。既有 `AnswerSlot` 保留相容名稱並成為 `AnswerRequirement` alias；`EvidenceContract` 現在執行 value type、entity、tenant/department/source、exact KB/document/release revision、authority、temporal、derivation、relation closure、minimum/exact cardinality 與 closed-scope proof。

`EvidenceState`、`ResponseAction`、`ExecutionStatus` 已正交；provider/schema/timeout/pack/internal failure 均回 `decision=error`、`response_action=escalate`，不可轉成 absent。Legacy coverage 只透過 adapter 產生新版 shape，尚未改變正式輸出。Trace redaction 只保留敏感值的 SHA-256 與 byte length。

## Review checklist

1. Canonical owner：只擴充 `query_plan.py`、`evidence_contract.py` 與 legacy adapter，沒有新增第二個 query router 或 decision aggregate。
2. 平行 authority：無；legacy coverage 仍維持現況 owner，KQ2 才切唯一 owner。
3. ACL/revision：contract 明確驗證 tenant、department、source、document revision、KB revision、Knowledge release 與 ACL flag。
4. Sync/stream/background/shadow：尚未接線，正式行為不變。
5. Execution failure：五類失敗測試皆不會變成 absent／安全拒答。
6. False acceptance/rejection：每個 scope/type/time/authority/relation 拒絕都有對應正例。
7. Migration：無 DB schema 變更。
8. Pack：pack failure 為獨立 execution status，不能偽裝缺資料。
9. Privacy：敏感 trace 欄位只留 hash/length；一般 log 不保存 quote/token/prompt。
10. Regression：KQ0、Knowledge engine、QueryPlan 與 KQ1 共 69 passed。
11. Rollback：revert KQ1 commit 即可；因未接 Live Ask，不需 runtime flag。
12. Evidence binding：以 KQ0 `KQ_BASELINE_MANIFEST.json` 的 exact release identity 為施工基線。
13. Shadow store：KQ1 不建立 store；KQ3 才驗證 out-of-band append-only contract。
14. Enforce authorization：不適用；未新增 flag、allowlist 或正式行為。

## 驗證

- `pytest tests/test_knowledge_answer_kq1.py tests/test_knowledge_engine.py tests/test_query_plan.py tests/test_knowledge_answer_kq0.py -q`：69 passed。
- KQ1 專用案例：21 passed，涵蓋正確／錯誤型別、entity、六種 scope/revision、時間邊界、authority、relation、cardinality、closed list、五種 execution failure、legacy adapter 與 trace redaction。
- Core contamination scan：271 files，0 unwaived findings。
- `compileall`、`git diff --check`：PASS。

## Review 決定

`PASS TO NEXT PHASE`

KQ1 未接管 Live Ask 且向後相容，允許進入 KQ2 唯一 Evidence Decision Engine。
