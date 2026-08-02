# Enclave 計畫進度看板

自動產生於 `2026-08-02T13:35:29.271919+00:00`（嚴格閘門；來源：`DEVELOPMENT_PLAN_TRIPLE_INJECTION.md`）。

- 計畫 checkbox：67/73
- **可驗證程式完成率：100.0%**（32/32，僅 category=code）
- template/mixed：40；人工閘門：1
- 閘門狀態：`PASS`
- 模式：`run_pytest=False` `max_age_hours=None`

## 假綠（計畫已勾但證據不足）

- （無）

## 全部出口條件

| Phase | Plan | Evidence | Cat | Detail | Item |
|---|---|---|---|---|---|
| 3.3 修復現有授權缺口 | [x] | — | mixed |  | `/kb/search` 必傳 `AuthorizationContext`（DD-C01） |
| 3.3 修復現有授權缺口 | [x] | — | mixed |  | 單筆／批次刪除走 `DocumentRevocationService`（tombstone + deny + wiki |
| 3.3 修復現有授權缺口 | [x] | — | mixed |  | Generate `document_ids`、Wiki 來源交集、Gateway connector object-l |
| 3.3 修復現有授權缺口 | [x] | — | mixed |  | 知識讀取統一入口 `RetrievalFacade`（KB／Chat／Generate／Agent；見 Phase 5  |
| 3.4 事件與一致性底座 | [x] | — | mixed |  | Outbox claim：`FOR UPDATE SKIP LOCKED` + stale `processing` 回 |
| 3.4 事件與一致性底座 | [x] | — | mixed |  | Wiki projection 失敗 raise／retry，不可吞錯標 completed（DD-H06） |
| 3.4 事件與一致性底座 | [x] | — | mixed |  | `document_processed` 與 `status=completed` 同交易；URL ingest 同樣補 |
| 3.4 事件與一致性底座 | [x] | — | mixed |  | RAGFlow：`created` 不投影內容；pending／parse 已 ingest → reconcile（D |
| 3.4 事件與一致性底座 | [x] | — | mixed |  | Partial unique indexes + duplicate report（`p1_dd_m04_unique_ |
| 3.6 Phase 0 出口條件 | [x] | OK | code | file present | 所有現有測試可在乾淨環境重現（`.github/workflows/ci.yml` 起 pgvector+redis 跑 |
| 3.6 Phase 0 出口條件 | [x] | OK | code | file present | KB model migration 可升級與回滾 |
| 3.6 Phase 0 出口條件 | [x] | OK | code | test file present (pass --run-pytest to  | DocumentList／檢索／Agent DocumentList 統一部門繼承 PEP（含祖先；僅 kb_admin |
| 3.6 Phase 0 出口條件 | [x] | OK | code | test file present (pass --run-pytest to  | 權限變更後舊 cache 不可命中（fingerprint 精確刪除或 ACL epoch bump；見 `tests/ |
| 3.6 Phase 0 出口條件 | [x] | OK | code | test file present (pass --run-pytest to  | Outbox 重送不產生重複 artifact（確定性 idempotency_key + converged skip |
| 3.6 Phase 0 出口條件 | [x] | OK | code | ok | 所有安全 Critical/High 問題有 owner 與關閉證據（見 `docs/security/FINDINGS |
| 4.6 Phase 1 出口條件 | [x] | OK | code | test file present (pass --run-pytest to  | 三個 mock adapter + HTTP adapter（respx）通過相同 contract test suit |
| 4.6 Phase 1 出口條件 | [x] | OK | code | ok | 下游端口只在內部 Docker network（compose profiles 改 expose；lite/stand |
| 4.6 Phase 1 出口條件 | [x] | OK | code | test file present (pass --run-pytest to  | Edge 剝離 X-Enclave-*；短效 HMAC service token 可 mint/verify；內部回呼 |
| 4.6 Phase 1 出口條件 | [x] | OK | code | test file present (pass --run-pytest to  | timeout、retry、circuit breaker、partial response 行為可測 |
| 4.6 Phase 1 出口條件 | [x] | OK | code | ok | object-level lineage 與 citation 完整（`artifacts/lineage_online |
| 4.6 Phase 1 出口條件 | [x] | OK | code | test file present (pass --run-pytest to  | deny-first deletion 測試通過 |
| 5.4 驗收 | [x] | OK | mixed | ok | 黃金集的 page、table、reading-order 指標有明確 baseline 與改善證據（`scripts/ |
| 5.4 驗收 | [x] | OK | code | test file present (pass --run-pytest to  | 解析失敗可回退且不重複寫入（`tests/test_plan_phase_gates.py`） |
| 5.4 驗收 | [x] | OK | code | test file present (pass --run-pytest to  | 任一 chunk 可回溯到原始頁面與 bbox（ParseChunk.page/bbox + 契約測試） |
| 5.4 驗收 | [x] | OK | code | test file present (pass --run-pytest to  | 模型／解析器版本升級可 A/B、回滾（`PARSER_CANARY` / feature flags） |
| 5.4 驗收 | [x] | OK | code | test file present (pass --run-pytest to  | RAGFlow specialist retrieval 未通過評測前不進 GA 預設路徑（`specialist_ga |
| 6.4 驗收 | [x] | OK | mixed | ok | 每個 GA Connector 通過共同認證套件（`certify_connector.py`：**nas_smb 通過 |
| 6.4 驗收 | [x] | OK | template | template/file present (not runtime proof | 來源看不到的內容在搜尋、聊天、Agent、Wiki 都看不到（統一 PEP + `eval_retrieval_gate |
| 6.4 驗收 | [x] | OK | code | ok | 撤權在 Gateway 立即拒絕，projection 在目標 SLA 內收斂（pilot e2e + deny-set |
| 6.4 驗收 | [x] | OK | code | test file present (pass --run-pytest to  | rename/move/delete/group membership 變更可正確同步（NAS reconcile re |
| 6.4 驗收 | [x] | OK | code | test file present (pass --run-pytest to  | 斷線重送不產生重複文件（content_hash + source_record_id 去重） |
| 6.4 驗收 | [x] | OK | template | template/file present (not runtime proof | 每個 Connector 有 support runbook 與測試帳號策略（`docs/runbooks/CONNEC |
| 7.4 驗收 | [x] | OK | code | test file present (pass --run-pytest to  | 六類 Wiki Page 均有 schema 與版本測試（`tests/test_plan_phase_gates.py |
| 7.4 驗收 | [x] | OK | code | ok | 更新、刪除、撤權會重編譯或隱藏受影響內容（`eval_wiki_graph_quality.py`） |
| 7.4 驗收 | [x] | OK | mixed | test file present (pass --run-pytest to  | Wiki/Graph 回答有完整原始引用（citation_map 契約） |
| 7.4 驗收 | [x] | OK | mixed | test file present (pass --run-pytest to  | 父子分塊資料模型、遷移與回滾完成（`p3_parent_chunk_001`） |
| 7.4 驗收 | [x] | OK | template | template/file present (not runtime proof | Wiki 品質、成本與 freshness 有可量測 SLO（`docs/slo/CUSTOMER_SLO_TEMPLA |
| 8.0 現況（2026-08-01） | [x] | — | mixed |  | 單一 `RetrievalFacade`（`app/services/retrieval_facade.py`）：強制  |
| 8.0 現況（2026-08-01） | [x] | — | mixed |  | KB `/search`、Chat orchestrator、Generate context、Agent `kb_se |
| 8.0 現況（2026-08-01） | [x] | — | mixed |  | `UnifiedRetriever` citation 改走 `gateway.citation.CitationBui |
| 8.0 現況（2026-08-01） | [x] | — | mixed |  | 架構守門測試：`tests/test_retrieval_facade_architecture.py` |
| 8.0 現況（2026-08-01） | [ ] | — | mixed |  | Wiki/Graph Web UI（仍 API-only；見 DD-M08） |
| 8.0 現況（2026-08-01） | [ ] | — | mixed |  | specialist retrieval GA 預設路徑（仍閘門關閉） |
| 9.0 產品決策（2026-08-01） | [x] | — | mixed |  | Review queue 有生產入佇列路徑（watcher → classifier → enqueue） |
| 9.0 產品決策（2026-08-01） | [x] | — | mixed |  | 核准觸發 ingest 不再重入 review |
| 9.4 Agent 驗收 | [x] | OK | code | test file present (pass --run-pytest to  | 未授權工具不可被模型提示繞過（allowlist + prohibited；`test_plan_phase_gates |
| 9.4 Agent 驗收 | [x] | OK | code | test file present (pass --run-pytest to  | 審批服務失效時寫入工具 fail closed（DB down → deny） |
| 9.4 Agent 驗收 | [x] | OK | mixed | test file present (pass --run-pytest to  | 重試不造成重複副作用（approve 冪等） |
| 9.4 Agent 驗收 | [x] | OK | code | test file present (pass --run-pytest to  | Sandbox 無法讀 host filesystem 或存取未授權網路（image allowlist + egres |
| 9.4 Agent 驗收 | [x] | OK | code | test file present (pass --run-pytest to  | UI 顯示動作與結果，不顯示 chain-of-thought（AgentEvent 無 CoT） |
| 9.4 Agent 驗收 | [x] | OK | code | ok | 任務完成率在具名任務集上量測，不使用模糊百分比（`eval_agent_tasks.py`） |
| 10.1 安裝與部署 | [x] | — | mixed |  | `docker-compose.prod.yml` 使用 `${IMAGE_PREFIX}/…:${IMAGE_TAG} |
| 10.1 安裝與部署 | [x] | — | mixed |  | Staging／Production CD：`--no-build`、migration 失敗即停、health 經 e |
| 10.1 安裝與部署 | [x] | — | mixed |  | Worker healthcheck 失敗回非 0（不再 `|| exit 0`） |
| 10.1 安裝與部署 | [ ] | — | mixed |  | Sidecar image 全面 pin digest（DD-M11；P2） |
| 10.1 安裝與部署 | [ ] | — | mixed |  | Compose overlays 收斂為 base + overlays（DD-M10；P2） |
| 10.5 商業版安全閘門 | [x] | — | mixed |  | CI Dependency Audit 納入 frontend `npm audit --audit-level=hig |
| 10.5 商業版安全閘門 | [x] | — | mixed |  | frontend high 弱點清至 0（lockfile 升級 + `react-router` override 8 |
| 10.5 商業版安全閘門 | [ ] | — | mixed |  | 外部滲透測試（人工閘門，仍未勾） |
| Pilot | [x] | OK | mixed | file present | 單一客戶環境可安裝、備份、升級、移除（腳本：`ops_lifecycle`/`n1_upgrade` + runbook |
| Pilot | [x] | OK | code | ok | RAGFlow + 至少一個真實 Connector 完成端到端（`artifacts/pilot_e2e_last_r |
| Pilot | [x] | OK | code | ok | 撤權／tombstone 後 get=404 且 search 不洩漏（同上 E2E：get_after_revoke= |
| Pilot | [x] | OK | template | template/file present (not runtime proof | 有 support bundle 與故障 runbook（`docs/runbooks/PILOT_SUPPORT.md |
| Beta | [x] | OK | mixed | ok | 第一批 GA Connector 認證完成（**nas_smb** `connector_cert_last_run.j |
| Beta | [x] | OK | code | ok | Wiki/Graph 有引用、版本、撤權與回滾（`eval_wiki_graph_quality.py`；真實 WeKn |
| Beta | [x] | OK | code | ok | 統一評測證明整合後優於 Enclave baseline（`scripts/eval_retrieval_gate.py |
| Beta | [x] | OK | code | ok | 無未處理 Critical/High 安全弱點（`security_findings_gate.py` → `artif |
| General Availability | [ ] | — | human | human gate | 外部滲透測試完成（**人工閘門**；不可用本機 smoke 替代） |
| General Availability | [x] | OK | mixed | file present | SBOM、LICENSE/NOTICE 產物完成（`LICENSE` + `generate_sbom.py` NOTI |
| General Availability | [x] | — | mixed |  | N-1 升級／回滾／備份還原**腳本與 dry-run**完成（`n1_upgrade.py` / `ops_lifec |
| General Availability | [x] | OK | template | template/file present (not runtime proof | SLO、容量、支援與生命週期政策**模板**發布（`docs/slo/CUSTOMER_SLO_TEMPLATE.md` |
| General Availability | [x] | OK | code | ok | 三個能力包均可獨立停用，Enclave 核心仍可安全運作（`e2e_module_disable.py` + facto |
| General Availability | [x] | OK | mixed | ok | 下游升級失敗不破壞 Enclave 公開 API 或客戶資料（stub 禁假收斂 + `chaos_sidecar_do |

## 施工指令

```bash
python scripts/plan_progress_gate.py --write-md --strict
python scripts/plan_progress_gate.py --run-pytest --max-age-hours 168 --write-md --strict
python -m pytest tests/test_p0_production_fixes.py tests/test_plan_phase_gates.py -q
```
