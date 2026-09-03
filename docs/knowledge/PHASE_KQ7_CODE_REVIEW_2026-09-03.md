# KQ7 Code Review — Evaluation、Runtime Controls 與 Release Gate

- 日期：2026-09-03
- Gate：`KQ-RELEASE-01`
- 實作 Review：**PASS**
- 正式 Release Gate：**PASS**

## Review 結論

KQ7 已將 parse、retrieve、select、applicability、completeness、conversation 六階段 trace 固定為可驗證 invariant。Evaluation summary 分列 false acceptance、false rejection、partial correctness、conflict correctness；provider、schema、timeout、Pack failure 不得進入安全拒答分母。Internal alpha、external beta 與 GA 的總分／各領域／critical-error 門檻均由同一 deterministic policy 執行。

既有 evaluation tables 與 PostgreSQL partial unique constraint 繼續提供 first-run evidence 能力。獨立 unfamiliar-question／holdout 測試可作額外 QA benchmark，但不屬於開發完成或發布阻斷條件。AIHR 已揭露案例另以 manifest 固定作 regression／neighbor。

Runtime 的必要控制是 deployment mode、tenant allowlist、stable traffic allocation、kill switch、release identity 與 rollback。客戶 Owner 的 append-only HMAC 簽章紀錄保留為選用 governance integration，預設關閉；未配置書面簽核不會阻擋 Shadow 或 Enforce。若主動啟用該 integration，原有 scope、期限、release identity 與 evidence digest 驗證仍會 fail closed。

Production compose 仍提供選用的獨立 authorization volume；web 僅 read-only mount，並把建置完成後的 backend/frontend sha256 image ID 注入 runtime identity。未啟用 authorization integration 時不需要簽章、發證或客戶文件。

## 驗證證據

- KQ0–KQ7、Pack、evaluation、production Shadow、SourceVerifier、chat 與 demo regression：全數 PASS。
- Frontend DecisionSummary／ChatPage：5 passed；TypeScript 與 Vite production build：PASS。
- Ruff（KQ7 修改與新增檔案）：PASS。
- Docker production compose render：PASS（example env + non-secret validation placeholders）。
- Production off-mode release：`kq7-complete-f08884d`，migration `knowledge_typed_relation_kq4_001`，health／TLS／登入／授權 API smoke PASS；3 tenants 與 37 documents 保留。
- Machine-readable report：`artifacts/knowledge/KQ7_RELEASE_READINESS_REPORT.json`。

## Release Gate 判定

程式實作與 Code Review 已通過。`KQ-RELEASE-01` 只採技術證據，獨立陌生題盲測與客戶 Owner 書面簽核均為選用活動，不再影響開發完成或發布判定。Production 可透過 mode、allowlist 與 kill switch 受控啟用，並保留一鍵回到舊 decision path 的能力。
