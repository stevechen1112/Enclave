# Phase KQ0 Code Review — 2026-09-03

結論：`PASS TO NEXT PHASE`
Phase：KQ0 基線凍結與 AIHR→Enclave Mapping
Review scope：本機 source/worktree、離線 Ask baseline、文件與 artifacts；不含正式環境操作
下一階段：允許開始 KQ1

## 1. Review 摘要

KQ0 的 repository 內工作已完成：建立 mapping ADR、KQ capability disposition、13 類離線 baseline、sync/stream API schema、15 條 source-anchored call graph、11 項 known failures、271 檔核心污染掃描與重建／驗證工具。Live Ask runtime、DB schema、正式資料、部署與 Input I9 均未修改。

`KQ-BL-01` 已由 2026-09-03 新鮮正式 read-only operator snapshot 解除。公開 release identity、容器 image digest、runtime、active KB revision、Knowledge Unit release/membership 與 Pack versions 已綁定；兩次資料摘要一致，production mutation=0。本機隔離 PostgreSQL的兩項先前 environment-blocked 測試亦已 2/2 通過。

## 2. 交付物

- Mapping ADR：`../adr/ADR-022-aihr-enclave-knowledge-decision-mapping.md`
- Capability disposition：`KQ_CAPABILITY_DISPOSITION.md`
- Baseline 說明：`KQ_BASELINE.md`
- Baseline manifest：`../../artifacts/knowledge/KQ_BASELINE_MANIFEST.json`
- API schema：`../../artifacts/knowledge/KQ_API_SCHEMA_SNAPSHOT.json`
- 呼叫圖：`../../artifacts/knowledge/KQ_CALL_GRAPH.json`
- Offline outputs：`../../artifacts/knowledge/KQ_BASELINE_OUTPUTS.json`
- Known failures：`../../artifacts/knowledge/KQ_KNOWN_FAILURES.json`
- Contamination scan：`../../artifacts/knowledge/KQ_CORE_CONTAMINATION_SCAN.json`
- 重建工具：`../../scripts/freeze_knowledge_answer_baseline.py`
- 正式唯讀取證：`../../scripts/inspect_kq0_release_readonly.py`
- Operator snapshot：`../../artifacts/knowledge/KQ_PRODUCTION_OPERATOR_SNAPSHOT.json`
- 測試：`../../tests/test_knowledge_answer_kq0.py`

## 3. 標準 Review 問題

### 1. 本 phase 改變哪個 canonical owner？

沒有改變 runtime owner。KQ0 只凍結現況並決定後續責任：EvidenceOrchestrator 於 KQ2 才能成為唯一 final decision owner；目前 Live Ask 仍由 `retrieval_coverage` 決定。

### 2. 是否新增平行 aggregate、retrieval、revision、citation 或 decision？

沒有。ADR-022 只預先判定 KQ4 可提出 `KnowledgeUnitRelationProjection`，且限制為既有 KnowledgeUnitRevision 的可重建 projection；本 phase 沒有建立 model、migration 或 runtime service。

### 3. tenant/department/source ACL、RLS、KB revision 與 deny-set 是否完整？

本 phase 未改這些路徑。現有 `KnowledgeUnitRecord active + KnowledgeUnitRevision ready + KnowledgeUnitRelease active + membership active` admission 已在 `knowledge_authority_read.py`，並由 asset visibility 檢查；KQ4 仍須補 exact revision/deny 的雙重驗證證據。正式 snapshot 已凍結目前 KB revision 與空的 Knowledge Unit release 狀態。

### 4. sync、stream、background、shadow 是否使用同一契約？

否，這是已凍結差距。sync 不呼叫 SourceVerifier；stream 依 mode 才呼叫；EvidenceOrchestrator 未接 Live Ask。KQ0 call graph 已完整記錄，目標由 KQ1–KQ3 收斂。

### 5. provider failure 是否可能被誤算為 absent／abstain？

是。KQ0 provider-failure fixture 重現 timeout→legacy `abstain` 形狀；登錄為 `KQ0-KF-004`，KQ1 必須以正交 ExecutionStatus 修正。

### 6. false rejection 與 false acceptance 是否都有測量？

KQ0 只凍結可重放案例，不宣稱正式量測。wrong scope/revision/conflict/insufficient-context 作 false-acceptance 候選；partial/absent 作 false-rejection 基線。正式分母與門檻依 KQ3 首跑前 threshold manifest。

### 7. migration、backfill、reprojection 是否 idempotent 且可恢復？

本 phase 沒有 migration/backfill/reprojection。ADR-022 要求 KQ4 relation projection 提供 fresh、upgrade、downgrade／forward recovery 與 idempotent reprojection 後才可通過。

### 8. Pack 停用／故障／移除是否 fail closed？

本 phase 未變 Pack runtime。現有 HR compatibility direct path 登錄為 `KQ0-KF-011` 與具名 waiver；KQ6 必須完成 disable/uninstall negative tests 才能解除。

### 9. trace、metrics 與 UI 是否洩漏機密或跨租戶 metadata？

新 artifact 只含 synthetic questions、source-relative paths、schemas、hashes、非秘密 release metadata 與歷史 IDs，不含 tenant content、使用者信箱、token、密碼或完整來源 quote。KQ3 out-of-band store 尚未實作。

### 10. 既有 Input、Ask、citation、delete/revoke 與 release rollback 是否回歸？

未修改 runtime，因此沒有行為變更；targeted tests 48 passed。兩個需要 PostgreSQL `localhost:5435` 的既有測試已於隔離 `enclave_test` profile 重跑並 2/2 passed，也沒有修改 Input I9。

### 11. 是否有明確 rollback 指令與停止條件？

本 phase 只新增 docs/scripts/tests/artifacts，未部署。fresh production baseline 與 mutation=0 已成立，因此允許 KQ1；若撤回本 phase，只需 revert 本 phase commit，不得刪除使用者既有工作樹變更。

### 12. 測試證據是否綁定 exact source commit、image、schema、KB revision 與 Pack versions？

Source commit、dirty manifest、runtime file hashes、tooling hashes、API schema、正式 images、current exact KB revision、Knowledge Unit release/membership 空集合與 Pack versions 均已綁定 `KQ_BASELINE_MANIFEST.json`。

### 13. Shadow diff 是否只寫入 tenant DB 外的 append-only 加密 store，且 retention、legal hold、purge audit 與管理端再授權完整？

不適用於 KQ0 implementation；尚未建立 KQ3 store。Task Plan v1.1 與 ADR-022 已保留硬性邊界，KQ3 Review 必須實證。

### 14. 進入 enforce 的 tenant 是否有獨立於候選／shadow 核准的有效 Owner enforce 授權？

不適用。本 phase 未建立 allowlist、shadow 或 enforce，八策也未被視為授權。

## 4. 測試與證據

| 驗證 | 結果 |
|---|---|
| `freeze_knowledge_answer_baseline.py --check` | 產物 hash PASS；Gate 回報 PASS TO NEXT PHASE |
| KQ0 專用測試 | 6/6 PASS |
| QueryPlan、production-shadow contract、Knowledge engine 非 DB 測試 | 48/48 PASS |
| 先前阻塞的 PostgreSQL tests | 隔離 `enclave_test` profile 重跑 2/2 PASS |
| Python compileall（新增 script/test） | PASS |
| Core contamination scan | 271 files；0 unwaived findings；10 named waivers |
| Live runtime／migration diff | 0 |
| Production DB/provider calls | 0 |

先前 environment-blocked 的 PostgreSQL 測試已以隔離 profile 補齊，沒有以正式 DB 代替。

## 5. 未解除阻斷與解除方式

### Fresh production identity

已由既有 `kachu` operator profile 在 process-wide/read-only barrier 下取得 backend/frontend/gateway image digest、deployment manifest、model/prompt/flags、active KB revision、Knowledge Unit release/membership、Pack versions、ACL/revision/deny 摘要，以及執行前後 row/digest mutation sentinel。

### PostgreSQL integration evidence

已啟動本機隔離 PostgreSQL `enclave_test` profile，兩個 environment-blocked 測試均通過；沒有連正式 DB 代替 test profile。

## 6. 結論

`PASS TO NEXT PHASE`

Repository KQ0 交付、fresh production identity、exact release binding、mutation=0 與 PostgreSQL integration evidence 均成立。允許開始 KQ1；此結論不授權部署 KQ3 Shadow 或 KQ7 controlled enforce。
