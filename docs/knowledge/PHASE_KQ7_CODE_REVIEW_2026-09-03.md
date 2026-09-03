# KQ7 Code Review — Sealed Evaluation、Owner Authorization 與 Release Gate

- 日期：2026-09-03
- Gate：`KQ-RELEASE-01`
- 實作 Review：**PASS**
- 正式 Release Gate：**BLOCKED — EXTERNAL EVIDENCE REQUIRED**

## Review 結論

KQ7 已將 parse、retrieve、select、applicability、completeness、conversation 六階段 trace 固定為可驗證 invariant。Evaluation summary 分列 false acceptance、false rejection、partial correctness、conflict correctness；provider、schema、timeout、Pack failure 不得進入安全拒答分母。Internal alpha、external beta 與 GA 的總分／各領域／critical-error 門檻均由同一 deterministic policy 執行。

既有 evaluation tables 與 PostgreSQL partial unique constraint 繼續擁有 first-run authority。新 gate 強制兩組 corpus hash 與 question hash 都不重疊、獨立 custodian、不可覆寫 first-run、每輪至少 200 題、四領域各 50 題與至少 20% mixed/abbreviation/code/cross-language。AIHR 已揭露案例另以 manifest 固定只能作 regression／neighbor，不得冒充 sealed first-run。

Runtime 現在要求 tenant Owner 的 append-only HMAC 簽章紀錄。Shadow 與 Enforce 是兩份不同紀錄；allowlist、平台 gate、合作關係或「八策」名稱都不會推定授權。每份紀錄綁 tenant、Ask scope、期限、資料使用範圍、backend/frontend digest、deployment manifest、KB revision、Knowledge release、Pack versions、prompt/model、rollback point、流量與停止條件。Enforce 另要求 Shadow、tenant acceptance、ACL negative、rollback drill、browser acceptance 五份 64-hex evidence digest。簽章錯誤、路徑穿越 ID、過期、release mismatch、scope 不符、未命中穩定流量分桶或 kill switch 都回 `off`。

Production compose 已提供獨立 authorization volume；web 僅 read-only mount，並把建置完成後的 backend/frontend sha256 image ID 注入 runtime identity。Operator 發證工具不接受 command-line secret，必須從 secret manager 注入 key；authorization audit 使用前一事件 hash 與 HMAC event hash。

## 驗證證據

- KQ0–KQ7、Pack、evaluation、production Shadow、SourceVerifier、chat 與 demo regression：全數 PASS。
- Frontend DecisionSummary／ChatPage：5 passed；TypeScript 與 Vite production build：PASS。
- Ruff（KQ7 修改與新增檔案）：PASS。
- Docker production compose render：PASS（example env + non-secret validation placeholders）。
- Production off-mode release：`kq7-off-3d94e7c`，migration `knowledge_typed_relation_kq4_001`，health／TLS／登入／授權 API smoke PASS；3 tenants 與 37 documents 保留。
- Machine-readable report：`artifacts/knowledge/KQ7_RELEASE_READINESS_REPORT.json`。

## Release Gate 判定

程式實作與 Code Review 已通過，但本地實作者不能自稱「獨立 custodian」、不能偽造兩輪全新 sealed first-run，也不能代表 tenant Owner 核准 Shadow／Enforce。因此 `KQ-RELEASE-01` 正確維持 BLOCKED，production `KNOWLEDGE_DECISION_MODE=off`，且沒有簽發任何 Enforce authorization。這是正式發布安全條件，不是 Codex 機器存取權不足。
