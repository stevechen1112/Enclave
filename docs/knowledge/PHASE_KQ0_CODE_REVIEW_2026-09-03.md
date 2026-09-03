# Phase KQ0 Code Review — 2026-09-03

結論：`BLOCKED`
Phase：KQ0 基線凍結與 AIHR→Enclave Mapping
Review scope：本機 source/worktree、離線 Ask baseline、文件與 artifacts；不含正式環境操作
下一階段：KQ1 不得開始

## 1. Review 摘要

KQ0 的 repository 內工作已完成：建立 mapping ADR、KQ capability disposition、13 類離線 baseline、sync/stream API schema、15 條 source-anchored call graph、11 項 known failures、271 檔核心污染掃描與重建／驗證工具。Live Ask runtime、DB schema、正式資料、部署與 Input I9 均未修改。

`KQ-BL-01` 仍為 `BLOCKED`，不是因 repository assertion failure，而是缺少 authorized operator 於 2026-09-03 對正式環境產生的新鮮 read-only snapshot。現有正式 evidence 來自 2026-08-24，且 repository 內另有不同 image／deployment identity 的 acceptance/predeploy artifacts，不能推定哪一組是目前正式 release。

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
- 測試：`../../tests/test_knowledge_answer_kq0.py`

## 3. 標準 Review 問題

### 1. 本 phase 改變哪個 canonical owner？

沒有改變 runtime owner。KQ0 只凍結現況並決定後續責任：EvidenceOrchestrator 於 KQ2 才能成為唯一 final decision owner；目前 Live Ask 仍由 `retrieval_coverage` 決定。

### 2. 是否新增平行 aggregate、retrieval、revision、citation 或 decision？

沒有。ADR-022 只預先判定 KQ4 可提出 `KnowledgeUnitRelationProjection`，且限制為既有 KnowledgeUnitRevision 的可重建 projection；本 phase 沒有建立 model、migration 或 runtime service。

### 3. tenant/department/source ACL、RLS、KB revision 與 deny-set 是否完整？

本 phase 未改這些路徑。現有 `KnowledgeUnitRecord active + KnowledgeUnitRevision ready + KnowledgeUnitRelease active + membership active` admission 已在 `knowledge_authority_read.py`，並由 asset visibility 檢查；KQ4 仍須補 exact revision/deny 的雙重驗證證據。因正式 release snapshot 尚缺，本題不能簽發 runtime PASS。

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

未修改 runtime，因此沒有行為變更；targeted tests 48 passed。兩個需要 PostgreSQL `localhost:5435` 的既有測試因服務未啟動而 environment blocked，沒有被算成 PASS，也沒有修改 Input I9。

### 11. 是否有明確 rollback 指令與停止條件？

本 phase 只新增 docs/scripts/tests/artifacts，未部署。停止條件已觸發：fresh production baseline 不存在，因此 Gate 保持 BLOCKED 並禁止 KQ1。若撤回本 phase，只需 revert 本 phase commit；不得刪除使用者既有工作樹變更。

### 12. 測試證據是否綁定 exact source commit、image、schema、KB revision 與 Pack versions？

Source commit、dirty manifest、runtime file hashes、tooling hashes 與 API schema 已綁定 `KQ_BASELINE_MANIFEST.json`。正式 image 只有 2026-08-24 historical evidence；current exact KB revision、Knowledge release 與 Pack versions 未綁定，因此本題 BLOCKED。

### 13. Shadow diff 是否只寫入 tenant DB 外的 append-only 加密 store，且 retention、legal hold、purge audit 與管理端再授權完整？

不適用於 KQ0 implementation；尚未建立 KQ3 store。Task Plan v1.1 與 ADR-022 已保留硬性邊界，KQ3 Review 必須實證。

### 14. 進入 enforce 的 tenant 是否有獨立於候選／shadow 核准的有效 Owner enforce 授權？

不適用。本 phase 未建立 allowlist、shadow 或 enforce，八策也未被視為授權。

## 4. 測試與證據

| 驗證 | 結果 |
|---|---|
| `freeze_knowledge_answer_baseline.py --check` | 產物 hash PASS；Gate 正確回報 BLOCKED |
| KQ0 專用測試 | 6/6 PASS |
| QueryPlan、production-shadow contract、Knowledge engine 非 DB 測試 | 48/48 PASS，另 2 個 DB tests deselected |
| 首次含 DB targeted run | 48 PASS、2 environment blocked；原因為 PostgreSQL `localhost:5435` connection refused |
| Python compileall（新增 script/test） | PASS |
| Core contamination scan | 271 files；0 unwaived findings；10 named waivers |
| Live runtime／migration diff | 0 |
| Production DB/provider calls | 0 |

測試結果明確區分 passed assertions 與 environment blocked；沒有把 unavailable PostgreSQL 算成成功。

## 5. 未解除阻斷與解除方式

### Blocker A：fresh production identity

由 authorized operator 在 process-wide/read-only barrier 下取得：backend/frontend image digest、deployment manifest、model/prompt/flags、active KB revision、Knowledge Unit release/membership、Pack versions、ACL/revision/deny identity，以及執行前後 row/digest mutation sentinel。

### Blocker B：PostgreSQL integration evidence

在隔離 PostgreSQL test profile 啟動後重跑兩個 environment-blocked 測試；不得連正式 DB 代替 test profile，也不得為取得 PASS 而略過 read-only barrier assertion。

## 6. 結論

`BLOCKED`

Repository 內 KQ0 施工品質可接受，但 `KQ-BL-01` 的正式 freshness 與 exact release binding 尚未成立。依 Task Plan 停止條件，KQ1 不得開始；下一步只能取得 fresh read-only operator snapshot 並補跑隔離 PostgreSQL integration evidence。
