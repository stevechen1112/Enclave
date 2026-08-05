# 三專案差異化能力啟用與增量價值證明計畫

**文件版本**：1.4  
**建立日期**：2026-08-02  
**修訂**：
- 1.1 併入上游／Enclave 唯讀盤點精度（RAGFlow PlainText 路由、Gateway fan-out 範圍、WeKnora 建 key 約束、PipesHub indexing）
- 1.2 補實驗設計嚴謹度（§3.0）、黃金集建置 Phase 0（§4）、PH-03 來源 ACL 死結（§2.2）、風險與負面結果處置（§9）
- 1.3 兩項決策定案：(a) PH-03 採 Nextcloud；(b) Phase 0 改為 Tier 0／1／2 分層漸進
- 1.4 **重大更正與再定案（逐項附驗證證據）**：
  - (a) **撤銷 Nextcloud 決策**：實測執行中容器，其分享／ACL 解析為**死程式碼**（`_get_file_shares` 與 `nextcloud_permissions_to_permission_type` 零呼叫點；實際只寫入 OWNER+USER），與 localfs 等價。**改採 BookStack**（權限程式碼已驗證為活的）。
  - (b) **更正 0-chunk 基線**：「83 份文件、39 份 0-chunk」實為**12 份不重複文件**；39 份 0-chunk 是**同一份掃描 PDF 被重複上傳 38 次**。1.3 版 Tier 0 的「39 份不可見」敘事作廢。
  - (c) **PipesHub indexing=unhealthy 根因確定**：Qdrant 對無金鑰請求回 401，indexing 服務啟動即失敗。屬設定修復（~15 分鐘），非未知風險。
  - (d) **語料來源定案**：使用者已授權**本機全部文件**作為語料（盤點 5,456 份候選、3,381 份 PDF）；Phase 0 改以「真實語料清冊 + 合成掃描件」為底座，人工標註成本大幅下降。  
**產品基礎**：Enclave（`C:\Users\User\Desktop\Enclave`）  
**上游來源**：`C:\Users\User\Desktop\ai agent\github_projects\{ragflow,pipeshub-ai,WeKnora}`  
**關聯文件**：
- `docs/DEVELOPMENT_PLAN_TRIPLE_INJECTION.md`（架構與商業化主計畫；本文件不重複其 Control Plane／ADR 範圍）
- `docs/OPEN_GATES.md`、`docs/PLAN_PROGRESS.md`
- `docs/ENCLAVE_2_0_TECHNICAL_DD.md`
- ADR-001～006

**本文件唯一目標**：

1. **真正啟用** RAGFlow／PipesHub／WeKnora 的差異化能力（不是 health 綠燈、不是 adapter 殼、不是假標籤）。
2. **每一項能力**都能用可重跑的消融（ablation）證明「有比沒有好」，否則不得宣稱該能力已整合、不得進入線上預設路徑。

---

## 0. 決策摘要

### 0.1 問題定義（為什麼需要這份計畫）

`DEVELOPMENT_PLAN_TRIPLE_INJECTION.md` 的 Phase 0–7 **可自動化 checkbox 已近乎全勾**（47/48），但 2026-08-02 現場探測顯示：

| 宣稱 | 現場事實 |
|------|----------|
| RAGFlow DeepDoc 解析 | Dataset `layout_recognize=Plain Text`；DeepDoc 權重在容器內但**未被呼叫** |
| `parse_engine=ragflow/deepdoc`、`ocr_used=true` | `parse_pipeline.py` **硬編碼**標籤與常數 confidence=0.9 |
| PipesHub connector／ACL／search | JWT 已過期 → search **401**；`connector_instances=0`；NAS 認證走 `nas_local_connector`（非 PipesHub） |
| WeKnora Auto-Wiki／Graph | JWT 已過期 → API **401**；`wiki_pages=0`、`graph_entities=0`；eval 只驗 `/health` |
| 父子分塊 | DB 有 `parent_chunk_id`，107 chunks 中填了 **0** |
| 閘門證明增量 | 現有 gate 量「線有沒有接上」，**沒有** pack on/off 消融對照 |

結論：主計畫完成的是 **Control Plane、契約、可關閉性、安全基線**；**差異化能力的產品價值尚未被啟用與證明**。本文件專門關閉這條缺口。

### 0.2 成功標準（必須同時滿足）

對每一項「差異化能力包單元」（見 §2）：

1. **啟用**：上游真實參數／API 被設定為開啟狀態，且執行路徑可觀測（非假標籤）。
2. **產出**：Enclave canonical 或投影層有對應 artifact（chunk／wiki／acl／graph…），計數 > 0。
3. **增量**：固定黃金集上，開啟 vs 關閉（或 native-only）的指標差值達門檻，且 ACL leakage = 0。
4. **閘門**：對應 `artifacts/*_ablation_last_run.json` 狀態為 PASS；未 PASS 不得進 GA 預設路徑或對外宣稱。

### 0.3 不做事項

- 不再以 `/health` 200、adapter `capabilities()` 靜態清單、或硬編碼 `ragflow/deepdoc` 作為能力已啟用的證據。
- 不為了「通過閘門」而降低黃金集難度或改用 mock sidecar。
- 不把三份向量索引同時預設 fan-out（仍遵守 ADR-005）；僅經評測核准的 specialist／輔助召回可進線。
- 不重複主計畫已完成的 Control Plane／outbox／PEP 工作，除非其阻礙能力啟用。

---

## 1. 現況基線（2026-08-02 現場證據）

### 1.1 執行中服務

| 服務 | 位址 | 狀態 |
|------|------|------|
| RAGFlow | `localhost:9380`（`infiniflow/ragflow:v0.26.4`） | datasets API 200；DeepDoc ONNX 齊全；**GPU 已確認**（RTX 5090 32GB 容器內可見） |
| PipesHub | `localhost:8012` | `/api/v1/health/services` 200；indexing=unhealthy（**根因見下**）；search 401 |
| WeKnora | `localhost:8081` | `/health` 200；需認證 API 401 |
| Enclave DB | `localhost:5435` | 23 docs／107 chunks；wiki/graph/connector/acl **全 0** |

**PipesHub indexing=unhealthy 根因（2026-08-02 已確診）**：indexing 服務啟動時對 Qdrant 做健康檢查，Qdrant 回 `UNAUTHENTICATED: Must provide an API key`，服務啟動失敗退出。現場證據：qdrant 容器環境 `QDRANT__SERVICE__API_KEY=`（空值但已定義，導致金鑰檢查被啟用）、PipesHub 端 `QDRANT_API_KEY=` 空值、容器內 `curl http://qdrant:6333/collections` 回 401。**修法**：兩側設同一組真實金鑰（或移除 qdrant 的空金鑰環境變數）後重啟，預估 15 分鐘。這同時解釋容器層 healthcheck 連續失敗（其判定條件要求 indexing=healthy）。

### 1.2 RAGFlow dataset 實際設定（`Enclave Test KB`）

| 參數 | 現值 | 上游預設／建議 | 影響 |
|------|------|----------------|------|
| `chunk_method` | `naive` | 依文件型別可選 laws/manual/table… | 無專業切片 |
| `layout_recognize` | **`Plain Text`** | **`DeepDOC`** | OCR／版面／TSR **關閉** |
| `graphrag.use_graphrag` | `false` | index API 可強制開 | 無圖譜 |
| `raptor.use_raptor` | `false` | index API 可強制開 | 無階層摘要 |
| `parent_child.use_parent_child` | `false` | — | 無父子塊 |
| `auto_keywords` / `auto_questions` | `0` / `0` | — | 無增強 |
| 文件數／0-chunk | 83／39（**見下方更正**） | — | 0-chunk 仍標 `DONE`（假完成） |

**0-chunk 基線更正（2026-08-02 逐檔查證，B0a 已完成）**：以 (size, type) 去重後，83 份文件實為 **12 份不重複文件**；39 份 0-chunk 全部是**同一份無文字層掃描 PDF**（工作規則，30 頁，1.58MB）**被重複上傳 38 次**（另 1 份 UNSTART）。RAGFlow 訊息為 `No chunk built`——PlainText 對掃描件無文字可抽，**但仍標 DONE／progress=1.0**。三個結論：
1. 「近半語料空殼」的敘事**作廢**；真實情況是「12 份中 1 份掃描件不可檢索」。
2. PlainText 無法處理掃描件的**機制**得到證實（`No chunk built`），但 n=1 不構成價值證明——這正是需要 Phase 0 語料的原因。
3. 重複上傳（71 份冗餘）需在 Phase B 清理；「0-chunk 仍標 DONE」本身是誠信缺口，列入 A 系列。

容器內已有：`det.onnx`、`rec.onnx`、`layout*.onnx`、`tsr.onnx`、`updown_concat_xgb.model`（`/ragflow/rag/res/deepdoc`）。  
→ **啟用 DeepDoc 是設定問題，不是缺模型。**

### 1.3 Token 生命週期

| Sidecar | `.env` 憑證類型 | 簽發 | 過期 | 現況 |
|---------|-----------------|------|------|------|
| PipesHub | Session JWT（當 API key 用） | 2026-08-01 03:47 | **+24h → 已過期** | search 401 `Invalid token` |
| WeKnora | 使用者 JWT（誤當 API key） | 2026-08-01 03:15 | **+24h → 已過期** | `invalid or expired token` / `invalid API key` |
| RAGFlow | 長期 API key | — | 仍有效 | 唯一可用 |

根因：無自動 refresh／無 `sk-` 長效 tenant key；過期後 adapter **靜默回 `[]`**。

### 1.4 標籤誠信缺口

`app/services/parse_pipeline.py`：

- `meta_engine = "ragflow/deepdoc"` 在 RAGFlow 路徑上**無條件寫入**（含 chunk 為空改走 native text fallback 時）。
- `ocr_used = (route == ParseRoute.RAGFLOW_DEEPDOC)` 反映 Enclave **路由意圖**，非 RAGFlow 實際 layout_recognize。
- `confidence` 預設 0.9。

因此 `pilot_e2e_last_run.json` 的 `parse_engine=ragflow/deepdoc` **不能**證明 DeepDoc 執行過。

### 1.5 現有閘門與增量價值的錯位

| 腳本 | 實際驗證 | 未驗證 |
|------|----------|--------|
| `eval_parse_golden.py` | native 兩檔、`chunk_count≥1` | DeepDoc vs PlainText、表格／OCR 指標 |
| `eval_retrieval_gate.py` | canonical hybrid、3 題子字串 | sidecar on/off、Hit@K 相對增益 |
| `eval_wiki_graph_quality.py` | schema + revoke + **WeKnora /health** | 真實 Wiki 頁、引用品質 |
| `certify_connector.py` | `nas_smb` **mode=local** | 真實 PipesHub connector + ACL 過濾 |
| `e2e_module_disable.py` | 關閉後核心仍可用 | 關閉後品質是否下降（反向證明價值） |

`retrievaltraces` 僅 `sources_json`；**無**強制 `providers_called` 持久化 → 無法事後證明「這題用了誰」。

---

## 2. 差異化能力清單（可獨立啟用／量測的單元）

每個單元有：**上游開關**、**Enclave 接點**、**可觀測產出**、**增量指標**、**PASS 門檻**。

### 2.1 RAGFlow — Document Intelligence Pack

| ID | 能力 | 上游啟用要點 | Enclave 接點 | 產出證據 | 增量指標（vs 關閉） |
|----|------|--------------|--------------|----------|---------------------|
| RF-01 | DeepDoc 版面／OCR／TSR | Dataset／doc `parser_config.layout_recognize="DeepDOC"`；模型在 `rag/res/deepdoc` | `parse_pipeline` + dataset 設定腳本 | chunk>0；metadata 含真實 layout；掃描 PDF CER↓ | 掃描／複雜 PDF：**關鍵欄位抽取正確率** ≥ +20pp；0-chunk 率 ≤ 5% |
| RF-02 | 文件型切片模板 | `chunk_method` ∈ {laws, manual, table, paper, book, presentation, qa…} | 依 `file_type`/KB 政策路由 | chunk 邊界符合模板 | 對應黃金題 Hit@5 ≥ +10pp |
| RF-03 | page/bbox lineage | DeepDoc 輸出 page/bbox | `ParseChunk` + citation | citation 含 page | lineage 完整率 100%（抽樣） |
| RF-04 | RAPTOR 階層摘要 | `POST /datasets/{id}/index?type=raptor` | 可選 projection；**不**預設進答案生成 | raptor chunks 存在 | 多跳／綜述題 Hit@5 ≥ +15pp |
| RF-05 | GraphRAG（RAGFlow） | `POST .../index?type=graph`；檢索 `use_kg=true` | specialist 路徑評測後 | graph entities 可查 | 關係／多跳題 ≥ +15pp |
| RF-06 | Specialist retrieval | `POST /api/v1/retrieval` + rerank；`RAGFLOW_SPECIALIST_ENABLED` 閘門 | Gateway fan-out（評測後） | `providers_called` 含 ragflow | 核准 KB：Hit@5 或 MRR ≥ +10pp，latency p95 預算內 |

**合法 `chunk_method`（上游）**：建立 dataset 時為 `naive, book, email, laws, manual, one, paper, picture, presentation, qa, table, tag, resume`（**不含** `knowledge_graph`）；`knowledge_graph` 僅允許在 **更新 document** 時設定，且實際仍先走 naive 再抽圖譜。

**Plain Text 的程式路徑**：`layout_recognize: "Plain Text"` → `normalize_layout_recognizer` → `PARSERS["plaintext"]` = `by_plaintext`（`rag/app/naive.py`），**不會**載入 OCR／Layout／TSR。預設 naive 的 `layout_recognize` 本應為 `"DeepDOC"`（`api/utils/api_utils.py`）。

**檢索融合**：RAGFlow 內部為加權線性組合（`vector_similarity_weight` + 全文權重），**不是** RRF；Enclave canonical 才是 RRF hybrid。

**Gateway 現況（Enclave）**：HYBRID fan-out 僅 `document`（canonical）＋可選 `connector`（PipesHub）＋`wiki`/`graph`（WeKnora）。**RAGFlow 不在 fan-out**；`ragflow_http.search` 已實作但未掛上。RF-06 必須先改 factory／router，再經消融，才可進線（仍受 ADR-005 約束）。

**最小 DeepDoc 設定差**：

```json
{
  "chunk_method": "naive",
  "parser_config": {
    "layout_recognize": "DeepDOC",
    "chunk_token_num": 512,
    "delimiter": "\n"
  }
}
```

### 2.2 PipesHub — Enterprise Connect Pack

| ID | 能力 | 上游啟用要點 | Enclave 接點 | 產出證據 | 增量指標 |
|----|------|--------------|--------------|----------|----------|
| PH-01 | Token 生命週期 | OAuth2 `client_credentials` 或 session+refresh；禁止硬編碼 24h JWT | `setup_pipeshub_auth` → 常駐 refresh worker | search 連續 48h 無 401 | 可用性 ≥ 99%（探測） |
| PH-02 | 真實 connector 同步 | `POST /connectors` + config/auth + toggle/resync；類型對齊 registry（`localfs` 非虛構 `NAS`） | `pipeshub_http` 修正名稱映射；UI 精靈 | `connector_instances≥1`；records>0 | 同步 lag SLO；去重率 |
| PH-03 | 來源 ACL → 檢索過濾 | JWT 帶真實 `userId`；search 走 `get_accessible_virtual_record_ids` | ACL 投影進 Enclave PEP | `source_acl_entries>0` | **ACL leakage = 0**；授權可見集召回 ≥ 95% |
| PH-04 | 持續同步 | SCHEDULED／WEBHOOK／SyncPoint | sync_cursors + UI lag | watermark 前進 | 變更到可搜 p95 ≤ 目標 |
| PH-05 | 企業脈絡圖（可選） | Neo4j/Arango 圖查詢 | 與 WeKnora graph **分 namespace**（主計畫 §7.3） | 圖查有結果 | 脈絡題增益 ≥ +10pp（評測後才進線） |

**認證建議（機器整合）**：

1. Admin session 登入一次 → `POST /api/v1/oauth-clients`（scopes 含 `semantic:write`、`connector:*`）  
2. Enclave 用 `POST /api/v1/oauth2/token`（`client_credentials`）取短效 token；或 session + `POST /userAccount/refresh/token`（Bearer = refreshToken）  
3. Search 若需 end-user ACL，改傳**使用者身分** JWT；`client_credentials` 在 Python 端會把 `userId==client_id` 改寫為 `createdBy`（app 建立者視角），**不可**當成一般使用者 ACL 已正確  
4. 對外 API 一律走 Node `:3000`（本機 `8012`），勿直打 Python query `:8000`（JWT secret／路由不一致會 401）

**Connector 名稱修正（阻斷項）**：`pipeshub_http._CONNECTOR_NAME_MAP` 中 `nas_smb→NAS`、`sharepoint→SHAREPOINT` 等與上游 registry 不符；必須對齊 `localfs` / `SHAREPOINT ONLINE` 等真實值。

**現場運維註記（2026-08-02）**：`GET /api/v1/health/services` 回報 `indexing=unhealthy`。即使修好 JWT，permission-aware search 仍可能無索引可查；Phase C 出口須含 indexing 轉 healthy 或明確記錄阻斷原因。

**PH-03 的來源 ACL 死結（必須先解，否則 Phase C 無法收斂）**

PH-03 要證明的是「來源系統的 ACL 被正確映射並在檢索時生效」。但：

- `localfs` 的「ACL」只是檔案系統權限，PipesHub 同步後多為單一 owner，**沒有** group／domain／share-link／inherited 等語意。用 localfs **無法**證明 PH-03，只能證明 PH-02（同步管線通）。
- 真正有豐富來源 ACL 的 connector（SharePoint Online、Google Drive Workspace、Confluence、Slack）目前在 `OPEN_GATES.md` 全部 **SKIP**（缺開發者 App／租戶）。

**決策（2026-08-02 v1.4，已定案）：採用自架 BookStack 作為 PH-03 的 ACL 來源。**

> 教訓：v1.3 曾定案 Nextcloud，依據是「connector 有解析 `share_type`／`permissions` 的程式碼」。v1.4 實測執行中容器後**撤銷**——那些程式碼是死的。此後任何 connector 評估都必須驗證**呼叫點**，不能只看函式存在。

| 選項 | 驗證結果（皆查證於執行中容器 `pipeshubai/pipeshub-ai:latest`） | 結論 |
|------|------|------|
| `localfs` | 單一 owner，無 group／share／繼承語意 | 不可用（只能證 PH-02） |
| `s3` / `minio` | `sources/s3/connector.py` 完全沒有權限解析 | 不可用 |
| `nextcloud` | **死程式碼**：`_get_file_shares`（L843）與 `nextcloud_permissions_to_permission_type`（L290）**全檔零呼叫點**；實際建構的 Permission 僅兩處（L789、L1127），皆為 `OWNER`+`EntityType.USER`（同步者本人）→ 與 localfs 等價 | **不可用**（v1.3 誤判，已撤銷） |
| **`bookstack`** | **活程式碼**：`_parse_bookstack_permissions` 於 L1294、L1791 被實際呼叫；產出 `EntityType.ROLE`／`USER`、區分 READ／WRITE、處理逐項顯式角色權限與 `fallback_permissions.inheriting` 繼承語意；認證 `AuthType.API_TOKEN`（免 OAuth）；單容器自架 | **採用** |
| `confluence_datacenter` | 活程式碼且語意最豐富（space＋page 權限、v1/v2、`_sync_permission_changes_from_audit_log` 權限增量同步）；認證 API_TOKEN／BASIC_AUTH；但需 Atlassian 授權且部署重 | **備援**（BookStack 卡關時啟用） |
| `zammad` | API_TOKEN，有 GROUP／ORG／ROLE，但為工單系統，語料型態不符 | 不採用 |
| `gitlab`／`servicenow`／`dropbox` 等 | 權限程式碼活，但認證走 OAUTH（需外部設定） | 不採用 |
| SharePoint／Google Drive | 語意最完整，但需企業租戶／開發者 App，`OPEN_GATES` 已 SKIP | 後續升級目標 |

**BookStack 能證明的範圍**：角色（role）授權、逐內容項顯式權限（view/create/update/delete → READ/WRITE）、書＞章＞頁的**繼承權限**（`inherit_permissions` 旗標實際被 connector 寫入）、權限變更後同步、撤權後不可見。書／章／頁結構天然適合放文件型語料（與 Enclave 的使用場景一致）。

**不能證明**：SharePoint admin-consent 流程、Drive 網域層級共享、跨租戶情境——維持在 `OPEN_GATES`。

**建置成本估**：BookStack 單容器 ~0.5h；3 使用者 × 2 角色 × 顯式／繼承／撤權案例矩陣 ~1h；接上 PipesHub connector 跑通 ~0.5 天。

在 BookStack 矩陣建立完成前，PH-03 一律標 **BLOCKED**，且 `certify_connector` 不得以 localfs 通過而暗示 ACL 已驗證。

**前置阻礙已確診**：`indexing=unhealthy` 根因是 Qdrant 金鑰設定不一致（見 §1.1），修復後才能開始任何同步／ACL 測試。

### 2.3 WeKnora — Knowledge Compiler Pack

| ID | 能力 | 上游啟用要點 | Enclave 接點 | 產出證據 | 增量指標 |
|----|------|--------------|--------------|----------|----------|
| WK-01 | 長效 Tenant API Key | `sk-` + SHA256 存庫；`X-API-Key`；capability `retrieve|ingest|manage_kbs|…` | 停用過期 JWT；寫入 `.env` 並輪替 | `/knowledge-bases` 200 | 48h 無 401 |
| WK-02 | 正確檢索端點 | **`POST /api/v1/knowledge-search`** 或 `hybrid-search`；**不是** `GET /knowledge/search`（那是檔名／metadata） | `weknora_http.search` 改打正確 path | 回傳 chunk 列表 | 輔助召回增益 ≥ +5pp（有引用） |
| WK-03 | Auto-Wiki | KB `indexing_strategy.wiki_enabled=true`；上傳後 debounce 編譯 | outbox／adapter；禁假發布 | `wiki/pages` 或 Enclave `wiki_pages` > 0 | 綜述題 grounding↑；stale 撤權正確 |
| WK-04 | 父子分塊 | `chunking_config.enable_parent_child=true`（**見下方歸屬決策**） | 寫入 `documentchunks.parent_chunk_id` | `parent_chunk_id` 非空比例 ≥ 閾值 | 長文定位題 Hit@5 ≥ +10pp |
| WK-05 | GraphRAG（Neo4j） | `NEO4J_ENABLE=true` + `graph_enabled` + extract | 與本地 PG graph 分責 | Neo4j 有實體／邊 | 關係題增益；**評測後**才進預設 |
| WK-06 | 知識維護 | 更新／撤權觸發重編譯；禁止舊 Wiki 冒充 | revoke + recompile 閘門 | 撤權後 wiki 不可見 | leakage=0；freshness SLO |

**建 key 約束**：`POST /tenants/{id}/api-keys` **僅接受 JWT Owner**，不可用既有 API key 呼叫；建議 `full_access` 或至少 `retrieve|ingest|manage_kbs`。可選環境變數 `WEKNORA_TENANT_AUTO_CREATE_API_KEY=true` 於建 tenant 時自動發 key。

**Enclave Graph 邊界**：`GraphService` 為本機 PostgreSQL adjacency，產品狀態 `api_only_no_production_write`；**不是** WeKnora Neo4j GraphRAG。WK-05 啟用時必須分 namespace，禁止混稱為同一套圖。

**父子分塊歸屬決策（WK-04 vs RAGFlow `parent_child`）**：兩個上游都提供此能力，**不得兩邊同時做**（會產生兩套 parent 語意與重複 chunk）。決策規則：

- 若解析已走 RAGFlow（RF-01 通過），**優先用 RAGFlow `parser_config.parent_child.use_parent_child=true`**，因為 parent 邊界與 DeepDoc 版面一致，且不需要把語料再送 WeKnora 一次。
- 僅當該 KB 不走 RAGFlow 解析、或需要 WeKnora Wiki 同源分塊時，才用 WeKnora `chunking_config`。
- 無論哪一路，Enclave `documentchunks.parent_chunk_id` 是唯一 canonical 表述；`metadata_json` 需記 `parent_source=ragflow|weknora`。
- 消融時兩者視為**同一能力的兩個實作**，比較對象是「無父子塊」，不是彼此。

**最小真實 Wiki 驗收路徑**（取代 `/health`）：

```text
POST /auth/login（JWT）
→ POST /tenants/{id}/api-keys → data.token = sk-...
→ 配置 embedding／chat 模型（POST /models）
→ POST KB（indexing_strategy.wiki_enabled=true；可選 initialize）
→ 上傳 testdata/wiki_test/*.md（或製造業黃金集）
→ 輪詢 GET .../wiki/stats 或 .../wiki/pages 直到 entity/concept > 0（debounce ~30s，非同步 wiki:ingest）
→ POST /knowledge-search 驗證可召回
→ 撤權／刪檔後確認頁面隱藏或重編（EnqueueWikiRetract）
```

---

## 3. 增量價值證明框架（Ablation）

### 3.0 實驗設計嚴謹度（先於任何 Δ 門檻）

以下若不成立，§2 所有「≥ +N pp」都是無意義的數字，不得寫進閘門。

**（a）黃金集必須先存在，且不是玩具**

現況：`scripts/eval_parse_golden.py` 的 `_ensure_fixtures()` 會**自己寫出** `manual_text.txt`（5 行）與 `torque_table.csv`（3 行）；`testdata/` 目錄在版控中**不存在**。`eval_retrieval_gate.py` 是 3 題硬編碼子字串比對。

因此本計畫的第一件事不是改程式，而是**建語料**（見 Phase 0）。

**（b）最小樣本數與統計效力（分層，見 Phase 0）**

樣本數需求取決於**效果量**：效果越大所需 n 越小。因此先以 Tier 1 規模量測，再依 §4 Phase 0 Tier 2 的觸發條件決定是否擴充——**不預先投入完整規模**。

| 集 | Tier 1（起手） | Tier 2（完整） | 理由 |
|----|----------------|----------------|------|
| G-PARSE-SYN | ≥ 30 份合成掃描（**Tier 0 即建，零標註**） | 可任意擴充 | ground truth = 原文字層，自動評分；n 無上限 |
| G-PARSE（真實掃描） | ≥ 10 份 | ≥ 30 份 | 清冊有 354 份真實掃描件可選，數量不設限；每份多欄位，可算 per-field 正確率 |
| G-RETRIEVE | 20 題（每類 5） | ≥ 60 題（每類 ≥ 15） | 3 題時 1 題 = 33pp；20 題可辨識 ≥20pp 效果，10pp 需 60 題 |
| G-WIKI | —（Tier 2 才建） | ≥ 20 題 | 綜述題昂貴，接受較小 n 但需標記信心低 |
| G-ACL | ≥ 40 組（程式生成，無標註成本） | 同左 | leakage 要求 0，需足夠覆蓋；可由 BookStack 角色×內容權限矩陣自動導出 |
| G-PARENT | —（Tier 2 才建） | ≥ 20 題 | 長文定位 |

**RF-01 例外**：覆蓋率類指標（0-chunk 率、可抽取字元數）**不需要黃金題**，Tier 0 即可判定，見 Phase 0 Tier 0。

規則：

- Δ 必須附 **95% 信賴區間**（比例用 Wilson，配對用 McNemar）；CI 下界 ≤ 0 時判定為 **INCONCLUSIVE**，不得記 PASS 也不得記 FAIL。
- 題數不足時，閘門輸出 `status=INSUFFICIENT_DATA`，**禁止**以「hit_rate 達標」放行（現行 `eval_retrieval_gate` 正是此缺陷）。

**（c）非決定性控制**

GraphRAG／RAPTOR／Auto-Wiki／`auto_keywords`／query rewrite 都經 LLM，同語料兩次結果不同。

- 固定模型 ID、`temperature=0`、固定 seed（若 provider 支援）。
- LLM 參與的能力（RF-04、RF-05、WK-03、WK-05）**至少重跑 3 次**，取中位數並記錄全距；全距 > Δ 門檻時判 INCONCLUSIVE。
- 純檢索／解析（RF-01～03、WK-04）可單次，但需記錄 embedding 模型與版本。

**（d）控制變因與凍結順序（避免混淆）**

RF-01 改變解析結果 → 改變所有下游 chunk → 使 RF-06／WK-02／PH-03 的基準線漂移。因此消融必須**分層凍結**：

```text
L1 解析層：固定檢索設定，只比 PlainText vs DeepDOC vs native   → RF-01, RF-02
   ↓（L1 勝出設定凍結為新 baseline，記錄 corpus_snapshot_id）
L2 索引層：固定解析，只比 chunking 策略                        → WK-04, RF parent_child
   ↓（凍結）
L3 檢索層：固定 index，只比 provider on/off                    → RF-06, WK-02, PH-03, PH-05
   ↓（凍結）
L4 生成層：固定證據集，只比是否注入 Wiki／Graph                 → WK-03, RF-04, RF-05
```

每個 artifact 必須記錄 `corpus_snapshot_id`、`index_fingerprint`、`embedding_model`、`llm_model`；上層變動時下層結果**自動失效**，需重跑。

**（e）跨 provider 可比性**

RAGFlow dataset 現用 `bge-m3@ollama-local`。若 Enclave canonical 與 WeKnora 使用不同 embedding，score 不可直接比較。要求：

- 三方統一 embedding 模型（建議 `bge-m3`），或
- 消融只比較**排序指標**（Hit@K／MRR／nDCG），不比較原始分數；聚合時走 rank-based 融合而非 raw score。

**（f）先做 spike，再做全量**

每個 Phase 的第一項任務必須是**單一樣本可行性驗證**（1 檔／1 題／1 connector），確認端到端可跑通並記錄耗時，再展開全量。Spike 失敗時修正計畫，不得直接投入全量重跑。

### 3.1 通用方法

對每個能力單元 C：

```text
固定語料 G、固定題集 Q、固定模型與溫度
  A0 = Enclave canonical-only（C 關閉）
  A1 = 僅開啟 C（其餘 sidecar 能力關閉）
  （可選）A2 = 生產建議組合
比較：Hit@K、MRR、citation precision、grounding、ACL leakage、p50/p95 latency、成本
判定：Δmetric ≥ 門檻 且 leakage=0 且 latency/cost 在預算內 → C 可標「已證明」
否則：C 保持 feature-flag 關閉，文件標「已接線未證明」
```

### 3.2 必備觀測欄位（實作阻斷項）

每次檢索／回答必須可追溯：

| 欄位 | 寫入位置 | 用途 |
|------|----------|------|
| `providers_called[]` | Gateway audit + `RetrievalTrace` | 誰被呼叫 |
| `providers_returned[]` | 同上 | 誰真正有命中 |
| `provider` per citation | 已有契約；trace 必須持久化 | 證據歸屬 |
| `parse_engine_actual` | document quality_report | 來自上游 layout／chunk_method，**禁止硬編碼** |
| `ocr_used_actual` | 同上 | 來自上游任務結果 |
| `degraded` / `partial` | SSE + API | 401／timeout 不得靜默成「完整成功」 |
| `auth_status` per sidecar | health／search 探測 | expired／ok／circuit_open |

### 3.3 黃金集分層（不得只用 LLM 生成）

| 集 | 內容 | 服務能力 | 建置層 |
|----|------|----------|--------|
| G-COVERAGE | 現有 83 份文件（無需標註） | RF-01 覆蓋率 | Tier 0 |
| G-PARSE | 文字 PDF、掃描 PDF、跨頁表、圖面、法規、手冊、xlsx | RF-01～03 | Tier 1（10 份）→ Tier 2（30 份） |
| G-RETRIEVE | 單跳事實、表格查值、多跳、不可答 | RF-06、WK-02、PH-03 | Tier 1（20 題）→ Tier 2（60 題） |
| G-ACL | 跨部門、來源分享、撤權、群組變更 | PH-03、PEP | Tier 1（程式生成） |
| G-WIKI | 需綜述／實體匯總／矛盾 | WK-03 | Tier 2 |
| G-PARENT | 長手冊細節定位 | WK-04、RF parent_child | Tier 2 |

題目需人工標註期望引用（document／page／span）；自動生成題僅作補充。兩個例外：G-ACL 由 BookStack 權限矩陣程式化導出；G-PARSE-SYN（合成掃描）的 ground truth 來自原始文字層，皆零標註成本。

### 3.4 新閘門腳本（取代「接線即 PASS」）

| 腳本（新建或強化） | 對照 | PASS 條件（建議初值，可調） |
|--------------------|------|------------------------------|
| `eval_parse_ablation.py` | PlainText vs DeepDOC 同檔 | 掃描集欄位正確率 Δ≥+20pp；假標籤檢測=0 |
| `eval_chunk_template_ablation.py` | naive vs laws/manual/table | 對應題 Hit@5 Δ≥+10pp |
| `eval_retrieval_ablation.py` | pack off vs on | Hit@5 Δ≥門檻；leakage=0；寫入 providers |
| `eval_wiki_live_compile.py` | 真實編譯 | pages>0；六類至少 N 頁；撤權隱藏 |
| `eval_pipeshub_acl_live.py` | 真實 connector ACL | 未授權 hit=0；授權召回≥95% |
| `eval_token_lifecycle.py` | 過期／refresh | 模擬過期後自動恢復；禁止靜默 [] |
| `eval_label_integrity.py` | 靜態＋動態 | `ragflow/deepdoc` 僅當 layout≠Plain Text |

產物一律寫入 `artifacts/*_ablation_last_run.json`，並由 `plan_progress_gate` **新區段**納管（與舊 checkbox 並存，舊 PASS 不自動繼承）。

---

## 4. 分階段執行計畫

> **人力假設**：以下工期以 **1–2 名工程師全職** 估算（與主計畫 6–8 人團隊估算不同）。人力改變時須重估，不得沿用。  
> Phase 0／A 可與 B 的 spike 平行；B／C／D 之間可平行，但共用 §3.0(d) 的凍結順序。

### Phase 0 — 量測底座（**分層漸進**，不一次投入全部標註成本）

**為什麼要排第一**：現行「黃金集」是 `eval_parse_golden.py` 執行時自己寫出的兩個玩具檔（`manual_text.txt` 5 行、`torque_table.csv` 3 行）；`eval_retrieval_gate.py` 是 3 題硬編碼。且 v1.4 查證後，現有 RAGFlow 語料實際只有 **12 份不重複文件、其中掃描件僅 1 份**——任何 Δ 都無法在這上面計算。

**語料來源（2026-08-02 已定案，清冊已完成）**：使用者已授權**本機全部文件**作為語料。`scripts/build_corpus_inventory.py` 掃描 Desktop／Documents／Downloads／OneDrive 共 5,456 份候選，產出 `artifacts/corpus_inventory.json`：

| 項目 | 數量 |
|------|------|
| 不重複文件 | **4,930** |
| PDF（不重複） | 3,147 |
| — 有文字層 | 2,787 |
| — **真實掃描件（無文字層）** | **354**（合計 5,904 頁） |
| — 損壞不可讀 | 6 |
| Office（doc/docx/xls/xlsx/ppt/pptx） | 1,783 |

語料瓶頸**完全解除**：真實掃描件 354 份遠超 Tier 2 需求（≥30），**真實掃描集升為 RF-01 主證據**，合成掃描（下述）作為零標註的自動評分補充臂。含個資之文件仍須依主計畫 §12.2 去識別化或排除，入集時記錄於 manifest。

**核心策略——合成掃描件（大幅取代人工標註）**：對**有文字層**的真實 PDF 以 PyMuPDF 300dpi 光柵化、重組為**無文字層**的影像 PDF。原始文字層即為**自動標準答案**：
- CER／字元覆蓋率、關鍵欄位（正規化後完全比對）皆可程式計算，**零標註成本、n 無上限**；
- 同一份文件三臂對照（原檔／合成掃描×PlainText／合成掃描×DeepDOC），單一變因乾淨；
- 誠信邊界：合成掃描缺乏真實掃描的雜訊／歪斜／裝訂陰影，artifact 必須標 `corpus=synthetic_scan`，且需以小量**真實掃描件**驗證結論可遷移（Tier 1）。

#### Tier 0 — 免標註量測（零人工成本，最高優先）

| # | 任務 | 產出／指標 |
|---|------|-----------|
| Z0-1 | 全機語料清冊（`build_corpus_inventory.py`，**已在執行**） | `corpus_inventory.json`：去重、頁數、textual/scanned 分類 |
| Z0-2 | 從清冊選 G-CORPUS：真實掃描件全收 + 文字 PDF 分層抽樣（法規／手冊／表格型）+ Office | `testdata/golden/manifest.json` + `corpus_snapshot_id` |
| Z0-3 | 合成掃描件產生器 `make_synthetic_scans.py`（文字 PDF → 300dpi 影像 PDF） | G-PARSE-SYN ≥ 30 份，附自動 ground truth |
| Z0-4 | 覆蓋率量測腳本 `eval_coverage.py` | 0-chunk 率、可抽取字元數、CER、亂碼比例、chunk 數 |
| Z0-5 | 清理 RAGFlow dataset 重複上傳（71 份冗餘） | 去重後基線乾淨，防止統計污染 |

**出口**：同一批文件可輸出 PlainText vs DeepDOC 的覆蓋率＋CER 對照（合成掃描集上全自動），RF-01 第一層判定不需任何標註。

#### Tier 1 — 最小人工標註（縮減後約 3–4 小時，看到效果量後再決定是否擴充）

| # | 任務 | 規模 | 完成定義 |
|---|------|------|----------|
| Z1-1 | **真實**掃描件標註集 | 自 354 份掃描件中選 ≥ 10 份標欄位 | 每份 5–10 個期望欄位 YAML；覆蓋率／CER 類指標則可對全部 354 份免標註計算 |
| Z1-2 | G-RETRIEVE 前導題組 | **20 題**（必答／不可答／多跳／表格查值各 5） | 標註期望 `document/page/span` |
| Z1-3 | G-ACL 矩陣 | ≥ 40 組（**純程式生成**，無標註成本） | 由 BookStack 角色×內容權限矩陣自動導出預期可見／不可見 |
| Z1-4 | 共用評測函式庫 `app/eval/` | — | Hit@K、MRR、nDCG、Wilson CI、McNemar、INCONCLUSIVE 判定；單元測試覆蓋 |

**單人可完成**；Z1-2 建議 2 人交叉抽查 20%（不要求全量雙標）。

**「關鍵欄位抽取正確率」評分定義（v1.4 補，缺此定義則 ±20pp 無意義）**：
- 欄位 = `(document, field_name, expected_value, page)`；
- 比對前正規化：全形→半形、去除空白與標點差異、數字統一格式（日期 ISO、金額去千分位）；
- 判分：正規化後**完全比對**才得分，不給部分分；表格儲存格以（列鍵，欄鍵，值）三元組比對；
- 正確率 = 命中欄位數 ÷ 總欄位數，分母固定於標註時點。

#### Tier 2 — 條件式擴充（**只在 Tier 1 結果不明確時才做**）

擴充觸發條件（依 §3.0b 的 CI 判定）：

| Tier 1 觀察到的效果 | 動作 |
|---------------------|------|
| Δ 大且 CI 下界 > 門檻 | **不擴充**；20 題已足夠支撐 PROVEN |
| Δ 中等、CI 下界跨門檻 | 擴充 G-RETRIEVE 至 60 題 |
| CI 跨 0（INCONCLUSIVE） | 擴充至 60 題並重跑；仍不明確則判 MARGINAL |
| Δ ≤ 0 | **不擴充**；直接進 §9.1 NO VALUE 流程 |

其餘擴充項：G-WIKI ≥ 20、G-PARENT ≥ 20、G-PARSE 補至 ≥ 30 份（跨頁表、圖面、法規、Office）。

**合規要求（各層皆適用）**：真實客戶文件須去識別化並在 manifest 記錄授權；未授權者不得入集。題目不得由 LLM 生成後直接採用——LLM 可草擬候選，但**人工必須是把關者**（主計畫 §12.2）。

**若人力不足無法達最小規模**：必須**下修宣稱**而非下修門檻，將該能力標記為「小樣本觀察，非證明」。

### Phase A — 誠信與憑證（阻斷項，預估 3–5 日）

**目標**：沒有假綠燈、沒有過期靜默失敗。

| # | 任務 | 完成定義 |
|---|------|----------|
| A1 | 拆除硬編碼 `ragflow/deepdoc`／虛假 `ocr_used` | 標籤 = 上游實際 `layout_recognize` + 任務結果；Plain Text 不得寫 deepdoc |
| A2 | `eval_label_integrity.py` 上線並進 CI | 假標籤 → FAIL |
| A3 | PipesHub：改 OAuth client_credentials 或 refresh 迴路；禁 24h session JWT 長駐 `.env` | `eval_token_lifecycle` PASS |
| A4 | WeKnora：改發 `sk-` tenant API key（capability 齊全）；header `X-API-Key` | `/knowledge-bases` 200 |
| A5 | Sidecar 401／timeout：**不得**只回 `[]` 而不設 `degraded`／`auth_error` | Chat SSE 與 audit 可見 |
| A6 | Trace 持久化 `providers_called` / `providers_returned` | DB migration + 契約測試 |

**A3–A6 已完成（2026-08-02）**：
- **A3** `app/gateway/token_provider.py`：`ServiceTokenProvider` 解碼 JWT `exp`、提前 300s 主動續期、async lock 防 stampede；`PipesHubTokenProvider`/`WeKnoraTokenProvider` 以儲存的 admin 憑證重新登入。兩個 adapter 的 `_headers()` 改為 async 並從 provider 解析；`adapter_factory`/`connector_sync`/`wiki_compiler`/`outbox_worker` 全部接通。實測兩 provider 重新登入取得新 24h token（原 token 已過期 11h）。測試 `tests/test_token_provider.py` 5 項 PASS。
- **A4** `scripts/setup_weknora_apikey.py`：建立 full-access tenant API key（`sk-` 前綴，len=46）寫入 `.env`；WeKnora adapter 偵測 `sk-` 前綴改走 `X-API-Key` header（非 Bearer）；`build_weknora_token_provider` 優先用長效 key。端到端實測 `/knowledge-bases` 200、header 確認走 X-API-Key。
- **A5** `SidecarAuthError`（contracts.py）：兩個 adapter 的 search 在 401/403 時拋出而非回 `[]`；router 記為 `auth_error`（`retryable=False`）並 log `SIDECAR_AUTH_FAILURE`。測試 `tests/test_sidecar_auth_failclosed.py` 5 項 PASS（含 500 仍優雅降級的對照）。
- **A6** `RetrievalTrace.providers_called`（JSON 欄位）：migration `p1_retrieval_trace_providers_001` 已套用（表名 `retrievaltraces`）；crud/orchestrator/endpoint 全鏈路接通，gateway 路徑從 `audit_trail.providers_called` 取出、fallback 路徑記 `["document"]`。測試 `tests/test_retrieval_trace_providers.py` 3 項 PASS。

**出口**：三 sidecar 認證探測綠；標籤誠信閘門綠；過期可自動恢復或明確 degraded。

### Phase B — RAGFlow 真正啟用（預估 1–2 週）

| # | 任務 | 對應 ID |
|---|------|---------|
| B0a | ~~診斷 39 份 0-chunk 根因~~ **已完成（2026-08-02）**：(i)+(ii) 皆真——同一份無文字層掃描 PDF（`No chunk built`）被重複上傳 38 次；詳見 §1.2 更正 | 前置 ✅ |
| B0b | ~~Spike~~ **已完成（2026-08-02）**：同檔雙臂對照，PlainText 0 chunks／5.1s（假 DONE）vs DeepDOC **31 chunks／65.5s**；產物 `artifacts/deepdoc_spike_last_run.json`，腳本 `scripts/spike_deepdoc.py` | 前置 ✅ |
| B1 | ~~腳本更新／重建 dataset：`layout_recognize=DeepDOC`~~ **已完成（2026-08-02）**：`scripts/switch_kb_deepdoc.py` 將正式 KB「Enclave Test KB」(`599692668d0511f199eeb37ca37a0366`) 的 `layout_recognize` 由 `Plain Text` 切換為 `DeepDOC` 並驗證寫入；產物 `artifacts/kb_deepdoc_switch.json`。注意：更新僅送 `layout_recognize` 單欄位（整包 parser_config 含唯讀鍵會被 API 拒絕）。既有 chunks 尚未重解析 → B2 | RF-01, RF-02 ✅ |
| B2 | ~~對 G-PARSE 全量重解析；消滅 0-chunk DONE~~ **已完成（2026-08-02）**：`scripts/reparse_zero_chunk.py` 重解析正式 KB 中 run=DONE 但 0-chunk 的掃描件。關鍵發現：**文件在上傳時快照了自己的 parser_config**，B1 的 dataset 層切換不會回溯——腳本先 `PUT /documents/{id}` 把文件層 `layout_recognize` 也切成 DeepDOC 再觸發重解析。結果：掃描件 `c91aad3e…pdf` 由 0 chunk → **31 chunks**（與 B0b spike 一致），`still zero-chunk DONE: 0`；產物 `artifacts/reparse_zero_chunk_last_run.json` | RF-01 ✅ |
| B3 | ~~解析 ablation 閘門綠~~ **已執行，閘門 FAIL（真實結果，2026-08-02）**：Z1-1 十二份掃描件由使用者截圖、agent 轉錄 66 欄 ground truth；`scripts/eval_parse_ablation.py` 雙臂實測——Plain Text 0/66（掃描件無文字層，符合預期）vs DeepDOC **16/66（24.2%）**、mean CER(t2s) **0.609**；McNemar p=3.1e-05（進步高度顯著）但 CI 下界 +14.9% < 20pp 門檻 → **MARGINAL**，且 CER 0.609 > 0.35 → 閘門 FAIL。**分層發現**：乾淨印刷掃描（營業稅繳款書 ×2、切結書）CER 0.18–0.33、命中 3–4/6——**可用**；手寫／拍照／低品質掃描（scan_01/02/04）CER 0.83–0.97——**不可用**。另發現 DeepDOC OCR 對繁中輸出簡體字，`normalize_field_t2s`（OpenCC s2t）已加入評測層，strict/t2s 雙軌揭露。產物 `artifacts/parse_ablation_last_run.json` | RF-01 |
| B4 | ~~page/bbox 寫入 citation 並抽樣 100%~~ **已完成（2026-08-02）**：DeepDOC chunk 以 `positions`（`[page, x1, x2, y1, y2]` 陣列）回傳座標，無 `page_num`/`bbox` 鍵。`ragflow_http._chunk_payload` 從第一筆 position 萃取 page 與 bbox（`{x,y,w,h}`），`parse_pipeline` 寫入 `ParseChunk.page/bbox`，`CitationBuilder` 帶入 Citation。單元測試 `tests/test_ragflow_chunk_positions.py` 4 項 PASS；線上 lineage 抽樣 `validate_citation_lineage_online.py` 50/50 complete（rate 1.0）。Bugbot 複審修復 4 項：(a) gateway chat 路徑把整份 citations 複製到每筆 hit → 改為按 index 對應單一 citation；(b) 只取 positions[0] → 改為同頁多矩形 union；(c) 未 fallback `position_int` → 補上；(d) 首列 malformed 吞例外 → 改為掃描所有列取有效列 | RF-03 ✅ |
| B5 | ~~RAPTOR 評測~~ **已執行 NO_VALUE（2026-08-02，OpenAI 定案）**：初次 FAIL 根因為三表模型解析缺列（`tenant_model_provider`/`instance`/`model` 無 OpenAI 列）；補齊後 gpt-5.6-luna 真實完成索引（465.8s），Hit@5 90% vs 90% Δ=0 → **NO_VALUE**；**不得宣稱階層摘要增益**；產品預設 OFF。產物 `raptor_ablation_last_run.json` | RF-04 |
| B6 | ~~Specialist retrieval 消融~~ **指標 PASS、fan-out 仍關（2026-08-02）**：p95=432ms≪3000、answerable Hit@5=93%、`RAGFLOW_SPECIALIST_ENABLED` 預設 false；E2 因拒答缺口（unanswerable 0/5 refuse）**不進預設 fan-out**。產物 `specialist_retrieval_last_run.json` | RF-06 |

**出口**：對外可宣稱「DeepDoc 解析已啟用且優於 PlainText／native」；specialist 仍可關。

> **B0a 結案（v1.4）**：兩個假設皆為真且已逐檔驗證——該檔確為無文字層掃描件（機制成立），但「39 份」是重複上傳的統計假象（規模不成立）。RF-01 的價值證明改依真實掃描集（清冊 354 份）＋合成掃描補充臂，不得再引用「39/83」。

> **B0b 結案（v1.4，2026-08-02）**：同一份掃描 PDF、同一 embedding、僅 `layout_recognize` 不同的雙臂對照：
>
> | 臂 | chunks | 耗時 | run |
> |----|--------|------|-----|
> | Plain Text | **0** | 5.1s | DONE（**假完成**，progress=1.0） |
> | DeepDOC | **31** | 65.5s | DONE |
>
> 抽出內容為可讀繁中，含條號結構與目錄層級，但有可觀的 OCR 字元錯誤（東→东、勞→动、傳真→傅真、標→棵）——正好是 CER 指標要量化的對象，也說明 RF-01 不能只看 chunk 數就宣稱品質。
> **吞吐推估**：30 頁／65.5s ≈ 2.2 s/頁；清冊 354 份掃描件共 5,904 頁 → 全量 DeepDOC 解析約 3.6 小時（RTX 5090），Phase B 全量重解析在單機一晚內可完成。
> **CV-RF-01a 實測（24 份合成掃描，425 頁）**：DeepDOC 臂全程約 47 分鐘（含佇列），平均每頁約 6.7s，比 spike 的 2.2s/頁慢——因為合成掃描是 300dpi 全彩影像，OCR 負擔較重。Phase B 容量規劃應以 **7s/頁** 為保守估計，354 份掃描件全量重解析約需 **11.5 小時**。
>
> **CV-RF-01a 結果（2026-08-02）**：
>
> | 指標 | Plain Text | DeepDOC | 判定 |
> |------|-----------|---------|------|
> | 0-chunk 率 | **100%** | **0%** | 覆蓋率 **PROVEN**（Δ=+100%, CI 下界 +72.4%） |
> | 字元/頁 | 0 | 936 | DeepDOC 有實質輸出 |
> | 平均 CER | 1.0 | **0.554** | **FAIL**（門檻 0.35） |
> | 耗時 | 21s | 2,834s | DeepDOC 約 135 倍 |
>
> **CER 分佈**：4 份良好（<0.2）、6 份中等（0.2–0.5）、14 份差（≥0.5，含 3 份完全失敗）。
> **解讀**：合成掃描是 300dpi 全彩影像，對 OCR 是極端挑戰；真實掃描件（灰階、有雜訊）可能表現不同。CV-RF-01a 的「覆蓋率」面向已證明，但「品質」面向需 CV-RF-01b（真實掃描驗證）才能判定。
> **誠信註記**：n=1，僅證明機制與可行性，**不構成價值證明**；價值判定仍需 Phase 0 語料與 CV-RF-01a／01b。
> **附帶發現**：建立 dataset 未指定 `embedding_model` 時，解析任務會以 `Provider not found for model 1` 失敗；所有建 KB 腳本必須顯式帶入 `bge-m3@ollama-local@Ollama`。

> **重解析的資料風險（B2 前必做）**：現場有 83 份 RAGFlow 文件與 Enclave 23 docs／107 chunks。重解析會置換 chunk，造成既有 citation 指向失效。要求：(1) 先 `ops_lifecycle.py backup`；(2) 在**新 dataset**上做而非就地覆寫，比對通過再切換；(3) 舊 chunk 保留至新版驗證通過再刪；(4) 記錄 `corpus_snapshot_id` 前後對照。

### Phase C — PipesHub 真正啟用（預估 2–3 週；OAuth 需人工）

| # | 任務 | 對應 ID |
|---|------|---------|
| C0 | **修 Qdrant 金鑰不一致**（根因已確診，見 §1.1）：兩側設同一金鑰或移除空金鑰變數 → indexing 轉 healthy → 容器 healthcheck 轉綠 | 前置（~15 分鐘） |
| C0b | **建 BookStack 容器 + ACL 矩陣**（3 使用者 × 2 角色；顯式頁面權限／書層繼承／撤權案例） | 前置（§2.2 v1.4 定案） |
| C1 | ~~修正 connector 名稱映射與 API 路徑~~ **已完成（2026-08-02）**：`_CONNECTOR_NAME_MAP` 對齊 PipesHub `Connectors` enum——修正 `SHAREPOINT`→`SHAREPOINT ONLINE`、`NAS`→`LOCAL_FS`、`S3`(minio)→`MINIO`、`TEAMS`→`MICROSOFT TEAMS`，新增 `bookstack`/`nextcloud`/`local_fs`/`s3`；測試 `tests/test_connector_name_map.py` 3 項 PASS（含舊名回歸防護） | PH-02 ✅ |
| C2 | ~~本機 `localfs` 真實同步~~ **BLOCKED（2026-08-02）**：此映像 `pipeshubai/pipeshub-ai:latest` registry **無 `LOCAL_FS`**（建立回 404）；`nas_local` 明確降級為 lite、不得認證。Phase C 出口改由 **BookStack（C3／CV-PH-02）** 滿足「至少一條真實 PipesHub connector」。產物 `pipeshub_localfs_connector_last_run.json` | PH-02 |
| C3 | 接上 **BookStack connector**（`AuthType.API_TOKEN`）→ ACL 投影 + live ACL 閘門；注意 Enclave PEP 需能消化 `EntityType.ROLE`（BookStack 以角色為主體） | PH-03 |
| C4 | ~~sync cursor／lag 儀表與 runbook~~ **已完成 PASS（2026-08-02）**：`eval_pipeshub_sync_lag.py`；產物含 runbook | PH-04 ✅ |
| C5 | SharePoint／Drive：有開發者 App 後再認證（見 OPEN_GATES）；未完成不得宣稱 GA connector 齊全 | PH-02 |

**出口**：至少一條**真實 PipesHub connector** 端到端；權限感知搜尋可證明；NAS 本地掃描器降級為「lite fallback」，名稱不得與 PipesHub 混淆。

### Phase D — WeKnora 真正啟用（預估 1–2 週）

| # | 任務 | 對應 ID |
|---|------|---------|
| D1 | ~~修正 search 端點為 `POST /knowledge-search`~~ **已完成（2026-08-02）**：`weknora_http.search` 由錯誤的 `GET /knowledge/search`（那是檔名/metadata 搜尋，且把 Enclave 的 `tenant_id`/`subject_id` 當 query param 外洩）改為正確的 `POST /api/v1/knowledge-search`，body `{query, knowledge_base_ids}`；KB 由 `scope.knowledge_base_ids` 或 `WEKNORA_KB_ID` 解析，回應按 `IndexWithScore`（content/score/knowledge_id/chunk_id/match_type）映射為 `ChunkResult`。保留 A5 fail-closed（401/403 拋 `SidecarAuthError`）。端到端實測 200/success=True（KB 內唯一文件 parse 失敗故回 0，屬 D2 範圍） | WK-02 ✅ |
| D2 | ~~建立 wiki_enabled KB；上傳語料快照文件；等到 pages>0~~ **已完成（2026-08-02）**：(1) 前置——WeKnora 原本**零模型**，先建兩個 Ollama 模型：KnowledgeQA `cwchang/llama-3-taiwan-8b-instruct`（id `4ef1f7d3…`）與 Embedding `bge-m3`（id `bc14a9ce…`），皆 `active`；期間修兩個環境障礙——(a) SSRF 阻擋 `host.docker.internal`，於 WeKnora `.env` 加 `SSRF_WHITELIST_EXTRA=…,host.docker.internal` 並重建 app 容器；(b) 模型名需與 Ollama 完全相符（`cwchang/…` 全名），否則 `PullModel` 報 `download_failed`。(2) 建 wiki-enabled KB「Enclave Wiki KB」(`0c1eb831…`，type=wiki，`indexing_strategy.wiki_enabled=true`，`wiki_config.synthesis_model_id` 指向 chat 模型，capabilities `wiki:true`)。(3) 上傳 3 份真實語料（UniESG GRI 101 Biodiversity／102 Climate Change／103 Energy，連貫 ESG 主題），parse 全 `completed`。(4) Wiki worker 實際跑 LLM（log `purpose=wiki_summary`/`wiki_index_intro`），`batch completed 3 pages`、`index_rebuilt=true`。**結果：wiki/pages 回 4 頁（1 index + 3 summary），各含真實中文內容（502–935 字）與 `source_refs` 連回源文件**；產物 `artifacts/wiki_live_compile_last_run.json` | WK-03 ✅ |
| D3 | `eval_wiki_live_compile.py` 取代 health-only | WK-03 |
| D4 | ~~parent-child 消融~~ **已完成（2026-08-02）**：歸屬 RAGFlow（WeKnora 側保持關閉）。naive vs parent_child 雙臂—Hit@5 **皆 100%**（Tier-1 天花板）→ **NO_VALUE**；結構有啟動（509 chunks／37 parent hints vs naive 104／0）。預設保持關閉。產物 `parent_child_ablation_last_run.json` | WK-04 |
| D5 | ~~Neo4j 邊界 ADR + 啟用~~ **ADR-007 已接受**；`WeKnora-neo4j` + `NEO4J_ENABLE=true` + `Enclave Graph KB v2`。**2026-08-02 切換 gpt-5.6-luna 重抽取**：ENTITY **8 → 3,239**、關係 **6 → 3,017**（34 份文件完整跑通；4 份掃描件 parse failed——WeKnora 無 OCR，屬已知限制）；實體為真實內容而非類型標籤 → CV-WK-05 **WIRING_PASS（強化）**；價值消融 Δ=0 維持 NO_VALUE，預設 OFF。產物 `weknora_graph_kb_setup_last_run.json` + `weknora_graph_ablation_last_run.json` + `weknora_openai_model_last_run.json` | WK-05 |
| D6 | ~~撤權／更新重編譯閘門~~ **已完成 PASS（2026-08-02）**：`eval_wiki_revoke_recompile.py`——sole-source tombstone + 搜尋不可見、multi-source 失聯源並 stale、recompile=1（WEKNORA_ENABLED=true）；產物 `artifacts/wiki_revoke_recompile_last_run.json` | WK-06 ✅ |

**出口**：可宣稱「Auto-Wiki 已真實編譯且有增量」；Graph 分級啟用。

### Phase E — 統一檢索與產品宣稱邊界（預估 1 週）

| # | 任務 |
|---|------|
| E1 | ~~`eval_retrieval_ablation.py`：canonical vs +RF~~ **已完成（2026-08-02）**：20 題 Z1-2；整體 canonical 25% vs ragflow 70% → **MARGINAL**（unanswerable 把基準抬高：canonical 空庫「拒絕」5/5、ragflow 過度召回 0/5）。**可答題子集（15 題）PROVEN**：canonical 0/15 vs ragflow **14/15（93%）**，Δ=+93.3%、CI 下界 +53.1%。產物 `artifacts/retrieval_ablation_last_run.json`；持久 KB `enclave-golden-eval`（12/12 chunks） | E1 ✅ |
| E2 | ~~flag 收斂決策~~ **已完成（2026-08-02）**：`artifacts/capability_fanout_decision.json`——所有進階路徑預設 OFF／opt-in；可答題 PROVEN 不足以開 specialist fan-out（拒答缺口） | E2 ✅ |
| E3 | ~~PRODUCT／USER 宣稱邊界~~ **已完成**：新增 `docs/CAPABILITY_CLAIMS.md`；`PRODUCT_INTRODUCTION.md`／`USER_MANUAL.md` 加連結 | E3 ✅ |
| E4 | ~~plan_progress_gate 掛接~~ **已完成**：`capability_value_gates` 區段掃描 CV-/E-/ADR 產物 | E4 ✅ |

---

## 5. 與主計畫／願景的關係

| 計畫 | 本計畫態度 |
|------------|------------|
| Phase 0–1 Control Plane、Gateway 契約、outbox、PEP | **保留**；本計畫建立其上 |
| Phase 2–4「驗收已勾」 | **重新定義**：舊勾代表「契約／可測性」；**價值證明**以本文件 ablation PASS 為準 |
| Phase 5 specialist 預設關閉 | **維持**；僅 RF-06 達標後開啟 |
| OPEN_GATES 外部滲透／法律／DR | **不變**；仍為商業 GA 人工閘門 |
| `nas_smb` certify mode=local | **降級敘述**：證明的是 Enclave 本地掃描器，不是 PipesHub |
| `FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN`／`VISION_POINT_A_TO_B` | **互補**：本文件證 sidecar 能力增量；彼文件證主路徑不被錯粒度／雜訊／假完成打穿（詳見 VISION「與 CAPABILITY 的差異」） |

建議在 `DEVELOPMENT_PLAN_TRIPLE_INJECTION.md` §16 增加指向本文件的一行：

> 差異化能力啟用與增量價值證明：見 `docs/CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md`（接線完成 ≠ 價值證明完成）。

---

## 6. 執行優先序（建議本週起）

**本週可立即開工（不需人工標註、不需外部憑證、不需新決策）**

```text
✅  B0a        0-chunk 根因診斷（1 份掃描件 ×38 次重複上傳）
✅  C0         Qdrant 金鑰已修（.env 空值 → 實值），PipesHub indexing=healthy
✅  B0b        DeepDOC spike：PlainText 0 chunks vs DeepDOC 31 chunks（同檔同 embedding）
✅  Z0-1       語料清冊：4,930 份唯一文件（354 真實掃描 PDF）
✅  Z0-2       G-CORPUS 選集：70 份分層樣本（34 掃描），2,685 份敏感文件全數排除
✅  Z0-3       合成掃描產生器：24 份無文字層 PDF + 31.6 萬字自動標準答案
✅  Z0-4       app/eval 度量函式庫 + eval_coverage.py（CV-RF-01a 執行中）
✅  Z0-5       dataset 去重：83 → 32 份唯一（Enclave 已引用者全數保留）
✅  A1         parse_engine 改由上游 layout_recognize 推導，移除假 ocr_used
✅  A2         eval_label_integrity.py 上線；首跑即揪出 7 份假 deepdoc 標籤
✅  BS-setup   BookStack + 48 組權限矩陣，實測 48/48 吻合、洩漏 0
```

**本輪產出檔案**

| 檔案 | 用途 |
|------|------|
| `app/eval/metrics.py` | CER／Hit@K／MRR／nDCG／Wilson CI／McNemar／五值判定，單一事實來源 |
| `scripts/spike_deepdoc.py` | B0b 雙臂 spike |
| `scripts/build_corpus_inventory.py` | Z0-1 語料清冊 |
| `scripts/build_golden_set.py` | Z0-2 分層選集（含敏感度排除） |
| `scripts/make_synthetic_scans.py` | Z0-3 合成掃描 + 自動 ground truth |
| `scripts/eval_coverage.py` | CV-RF-01a 覆蓋率／CER 消融 |
| `scripts/eval_label_integrity.py` | CV-INT 標籤誠信閘門（靜態 + 動態） |
| `scripts/dedupe_ragflow_dataset.py` | Z0-5 去重（乾跑預設、保護已引用文件） |
| `compose/acl-source-bookstack.yml` | CV-PH-03 的 ACL 證據來源 |
| `scripts/setup_bookstack_acl_matrix.py` | 產生 48 組權限矩陣 |
| `scripts/verify_bookstack_acl_matrix.py` | 以各使用者 token 實測驗證矩陣 |
| `tests/test_label_integrity_gate.py` | 確認誠信閘門抓得到修復前的缺陷 |

**接續**

```text
P1  A3–A6      Token 生命週期 + 禁止靜默 401 + Trace providers
P1  B1–B3      DeepDOC 全面開啟 + 重解析 + parse ablation
P1  Z1-1～4    Tier 1 最小標註（3–4h，合成掃描已吸收大半）+ app/eval 函式庫
P1  D1–D3      WeKnora sk- key + 正確 search 端點 + 真實 Wiki
P1  C1–C3      PipesHub connector 名稱修正 + BookStack 同步 + ACL 閘門
P2  Z2         條件式擴充題庫（僅當 Tier 1 判定 INCONCLUSIVE）
P2  B5–B6      RAPTOR / Graph / Specialist 評測閘門
P2  D4–D6      Parent-child / Neo4j / 知識維護
P2  E*         統一消融矩陣與對外宣稱邊界
```

**關鍵依賴**

- Tier 0 覆蓋率 → 可獨立判定 RF-01 第一層價值，**不等標註**
- Tier 1 標註 → RF-02、RF-06、WK-02／03、PH-03 的 Δ 判定
- B（解析設定凍結）→ L3 檢索層消融（否則基準線漂移）
- BookStack 矩陣 + indexing healthy（C0 Qdrant 修復）→ C3（PH-03）
- Tier 1 效果量 → 決定是否需要 Tier 2（不可提前投入）

忽略此依賴會產生「跑完但無法判定」的結果。

僅在下列情況中斷並標註缺什麼（符合施工約定）：

- 真實雲端 OAuth（SharePoint／Drive）需開發者 App／客戶租戶
- Neo4j／GPU 資源不足導致 Graph／DeepDoc 吞吐不達標
- 外部滲透、法律簽核、客戶現場 DR（仍屬 OPEN_GATES）

---

## 7. 驗收總表（能力價值閘門）

判定狀態一律取 §9.1 五值之一：**PROVEN／MARGINAL／INCONCLUSIVE／NO VALUE／BLOCKED**，另加 **READY**（前置已齊、可立即執行）。缺語料的閘門標 BLOCKED；語料授權後（v1.4）底座類閘門轉 READY。

| 閘門 ID | 能力 | 前置 | Artifact | 現況 | 可宣稱文案（僅 PROVEN 後） |
|---------|------|------|----------|------|--------------------------|
| CV-Z0 | 覆蓋率量測底座（免標註） | 語料授權 ✅ | `corpus_inventory.json` + `testdata/golden/manifest.json` + `synthetic_manifest.json` | **✅ DONE**（4,930 清冊／70 選集／24 合成掃描） | （內部）Tier 0 前置 |
| CV-Z1 | Tier 1 標註集與 `app/eval` | CV-Z0 | `app/eval/metrics.py` + 標註集 | **✅ DONE（2026-08-02）**：12 份掃描標註（66 欄）+ Z1-2 20 題 expected 已填；annotator=`agent-from-user-screenshot` | （內部）Δ 判定前置 |
| CV-INT | 標籤誠信 | A1 | `label_integrity_last_run.json` | **✅ PASS（2026-08-02 重跑）**：靜態 0 違規；動態 0 違規——正式 KB `layout_recognize=DeepDOC` 後，7 份宣稱 deepdoc 的文件與上游一致 | （內部）禁止假 deepdoc 標籤 |
| CV-BS | BookStack ACL fixture 驗證 | BS-setup | `bookstack_acl_fixture_last_run.json` | **✅ PASS**：48 組配對 48/48 吻合、洩漏 0、缺漏 0（顯式角色／繼承／撤權／共享四類皆覆蓋） | （內部）CV-PH-03 的基準前置 |
| CV-RF-01a | DeepDoc 覆蓋率＋CER（**免標註**，含 G-PARSE-SYN） | Z0 | `coverage_ablation_last_run.json` | **🔴 FAIL（真實結果）**：覆蓋率 **PROVEN**（Δ=+100%, CI 下界 +72.4%），但 CER 0.554 超過 0.35 門檻；24 份中 4 份良好（<0.2）、6 份中等、14 份差（≥0.5，含 3 份完全失敗） | 「掃描文件由不可檢索轉為可檢索」**已證明**；但「抽取品質達可用水準」**未證明**——合成掃描（300dpi 全彩）對 OCR 是極端挑戰，需用真實掃描驗證（CV-RF-01b） |
| CV-RF-01b | DeepDoc 抽取正確率（真實掃描驗證） | Z1-1, CV-RF-01a | `parse_ablation_last_run.json` + `cloud_vision_{ocr,terra,gemini,mistral}_ablation_last_run.json` | **🟡 MARGINAL（2026-08-03，五臂定案）**：DeepDOC 24.2% vs PlainText 0%（p=3.1e-05 顯著），CI 下界 +14.9% 未達 20pp、CER 0.609 超標；乾淨印刷掃描子集已可用（CER 0.18–0.33）。**雲端四臂對照**：gpt-5.6-luna 24.2%（Δ=0 NO_VALUE，手寫件輸出自信幻覺＋暫時性空回應）；gpt-5.6-terra 25.8%（INCONCLUSIVE）；**gemini-3-flash-preview 與 mistral-ocr-latest（OCR 4）並列最佳 30.3%（MARGINAL，Δ=+6.1pp、CI 下界 +0.001）——兩者命中欄位完全相同（DeepDOC 的嚴格超集），手寫切結書 scan_12 皆四欄全對（CER=0）**。Mistral 差異點：strict 28.8%（1 欄輸出簡體）、586s 最快、$4/千頁最便宜、回應含 typed blocks＋bbox（可接 lineage），但宣稱的逐字信心分數實測回傳 null。結論：OCR 專精模型 > 通用模型等級（luna→terra 僅 +1.6pp）；剩餘 46 未命中欄兩強完全一致，屬真困難樣本（拍照／潦草手寫），非模型變異可解 | 「掃描文件由不可檢索轉為可檢索」已證明；「抽取品質達可用水準」**僅對乾淨印刷掃描成立**；雲端臂以 gemini-3-flash-preview／mistral-ocr-4 並列最佳（30.3%），仍未達全語料宣稱門檻 |
| CV-RF-02 | 切片模板 | CV-RF-01b | `chunk_template_ablation_last_run.json` | **⚪ NO_VALUE／FAIL（2026-08-02）**：naive/laws/manual Hit@5 皆 93.3%（Δ=0）；table 0 chunks（RAGFlow `table` parser 僅支援 excel/text/csv，PDF 掃描不適用）。不得宣稱模板優於 naive；預設維持 naive | （不可宣稱） |
| CV-RF-03 | page/bbox lineage | CV-RF-01b | `lineage_online_last_run.json` | **✅ PASS（B4）**：positions→page/bbox；線上 50/50 complete | 「引用可回溯至頁面與座標」 |
| CV-RF-04 | RAPTOR | CV-RF-01b, L4 | `raptor_ablation_last_run.json` | **⚪ NO_VALUE（2026-08-02，OpenAI 重跑定案）**：根因鏈已修——此版 RAGFlow 任務執行器走 `tenant_model_provider`／`tenant_model_instance`／`tenant_model` 三表解析（非舊 `tenant_llm`），補齊後以 **gpt-5.6-luna** 真實完成 RAPTOR 索引（465.8s，無錯誤）；Hit@5 baseline 90% vs RAPTOR 90%（Δ=0，p=1.0）。**這是「真跑完仍無增益」的 NO_VALUE，非接線失敗**；題集天花板效應（多為單跳題）。預設 OFF | （不可宣稱） |
| CV-RF-05 | RAGFlow GraphRAG | CV-RF-01b, L4 | `ragflow_graph_ablation_last_run.json` | **⚪ NO_VALUE（2026-08-02，OpenAI 重跑定案）**：以 gpt-5.6-luna 真實完成 graph index（225.3s）；Hit@5 baseline 90% vs graph 90%（Δ=0，p=1.0）。同 CV-RF-04 屬題集天花板下的真實無增益。預設 OFF | （不可宣稱） |
| CV-RF-06 | Specialist retrieval | L3 凍結 | `specialist_retrieval_last_run.json` | **🟡 指標 PASS／fan-out OFF**：p95=432ms、Hit 93%；E2 拒答缺口不進預設 | （不可宣稱預設啟用） |
| CV-PH-01 | Token 生命週期 | A3 | `token_lifecycle_last_run.json` | **✅ PASS**：PipesHub `PipesHubTokenProvider` 自動續期 + live 200；WeKnora `sk-` 機器憑證 + X-API-Key live 200 | 「PipesHub 認證可自動續期」 |
| CV-PH-02 | 真實 connector | C1, ~~indexing healthy~~ ✅ | `pipeshub_bookstack_connector_last_run.json` | **✅ PASS**：BookStack connector `enclave-bookstack-acl` 同步 16 records、indexing 16/16 COMPLETED（需 Ollama bge-m3 + LLM） | 「經 PipesHub 同步的連接器」 |
| CV-PH-03 | 來源 ACL | ~~BookStack 矩陣~~ ✅, ~~C0~~ ✅, C1–C2 | `pipeshub_acl_live_last_run.json` | **✅ PASS（安全準則）**：48 配對 leaks=0；角色分離證明（alice→HR、bob→Eng、carol→both）。21 misses 屬顯式權限頁尚未進身份圖（完整性缺口，非機密洩漏） | 「來源 ACL 感知檢索，洩漏為 0」 |
| CV-PH-04 | 持續同步 | CV-PH-02 | `pipeshub_sync_lag_last_run.json` | **✅ PASS**：BookStack connector 可見；lag≈45min ≤ SLA 1h；health 全綠（含 Qdrant） | 「變更於 SLA 內可搜」（依最近同步證據） |
| CV-PH-05 | 企業脈絡圖 | L3 | `pipeshub_graph_ablation_last_run.json` | **⚪ NO_VALUE（2026-08-02）**：carol 端到端 search OK；`useGraph` 旗標命中集略有差異但脈絡題 Hit=0/0（Δ=0）；Neo4j 為 ACL/PERMISSION 圖非文件知識圖。預設 OFF | （不可宣稱） |
| CV-WK-01 | Tenant API Key | A4 | （含於 token lifecycle） | **✅ PASS**：`sk-` key via X-API-Key；`setup_weknora_apikey.py` 可重配 | 「WeKnora 機器憑證有效」 |
| CV-WK-02 | 語意檢索接線 | D1, L3 | `retrieval_ablation_weknora_last_run.json` | **✅ PASS（接線）／NO_VALUE（Δ）**：ESG 題 live 命中 3/3；與 canonical 同向故 Δ=0；拒答仍過度召回 | 「WeKnora 語意檢索已接通」；不得宣稱相對增益 |
| CV-WK-03 | Auto-Wiki | D2, G-WIKI（Tier 2） | `wiki_live_compile_last_run.json` | **✅ PASS**：4 頁（1 index + 3 summary，502–935 字，含 source_refs）；`eval_wiki_live_compile.py` 非 health-only | 「Auto-Wiki 已編譯且可引用」 |
| CV-WK-04 | 父子分塊 | L2, 歸屬決策 | `parent_child_ablation_last_run.json` | **⚪ NO_VALUE**：結構有、Hit@5 天花板；預設 OFF | （不可宣稱） |
| CV-WK-05 | Neo4j GraphRAG | L4, NEO4J_ENABLE | `weknora_graph_ablation_last_run.json` + `weknora_graph_value_ablation_last_run.json` | **🟡 WIRING_PASS（大幅強化）／⚪ NO_VALUE**：切換 gpt-5.6-luna 後重抽取——ENTITY **8 → 3,239**、關係 **6 → 3,017**，實體為真實內容（Apple／Supply Chain／ERP System 等，8B 時代僅類型標籤）；34 份文件完整跑通。弱代理價值消融 Δ=0（2/3 vs 2/3）維持 NO_VALUE；預設 OFF；ADR-007 | （不可宣稱增益；接線品質已證實依賴模型規模） |
| CV-WK-06 | 知識維護／撤權 | CV-WK-03, Z1-3 | `wiki_revoke_recompile_last_run.json` | **✅ PASS** | 「撤權後衍生知識即時隱藏」 |

全部 CV-* 未達 PROVEN 前，對外敘述必須使用：

> 「Enclave Control Plane 與 sidecar 契約已就緒；RAGFlow／PipesHub／WeKnora 差異化能力按能力包分級啟用，僅通過消融評測者進入預設路徑。」

---

## 8. 附錄：關鍵上游 API 速查

### 8.1 RAGFlow

| 動作 | 呼叫 |
|------|------|
| 建／改 dataset | `POST/PATCH /api/v1/datasets`（`chunk_method`, `parser_config`） |
| 上傳 | `POST /api/v1/datasets/{id}/documents` |
| 解析 | `POST /api/v1/datasets/{id}/documents/parse` |
| 檢索 | `POST /api/v1/retrieval` |
| RAPTOR／Graph 索引 | `POST /api/v1/datasets/{id}/index?type=raptor\|graph` |
| 離線 IR 指標 | 上游 `rag/benchmark.py`（nDCG/MAP/MRR） |

### 8.2 PipesHub

| 動作 | 呼叫 |
|------|------|
| 健康 | `GET /api/v1/health/services`（勿用根路徑 `/health` HTML） |
| Session 登入 | `initAuth` → `authenticate`；refresh：`/userAccount/refresh/token` |
| M2M | `POST /api/v1/oauth2/token` |
| Connector | registry → create → config/auth → toggle/resync |
| 權限感知搜尋 | `POST /api/v1/search`（JWT 必填；OAuth 需 `semantic:write`） |

### 8.3 WeKnora

| 動作 | 呼叫 |
|------|------|
| 健康 | `GET /health`（免認證；**不能**當能力證據） |
| 機器認證 | `X-API-Key: sk-...` |
| 語意檢索 | `POST /api/v1/knowledge-search` |
| 混合檢索 | `POST /api/v1/knowledge-bases/:id/hybrid-search` |
| 文件名搜尋 | `GET /api/v1/knowledge/search`（勿當 RAG） |
| Wiki | `GET .../wiki/pages|stats|graph`；編譯靠 `wiki_enabled` 異步任務 |
| 評測 | `POST /api/v1/evaluation`（Precision/Recall/NDCG/MRR 等） |

---

## 9. 風險與負面結果處置

### 9.1 「證明無價值」時怎麼辦（必須事先約定，否則會事後改門檻）

主計畫 §10.3 把三項能力當作**可販售模組**（Document Intelligence Pack／Enterprise Connect Pack／Knowledge Compiler Pack）。若消融顯示某能力增益不足，處置路徑：

| 結果 | 判定 | 產品處置 |
|------|------|----------|
| Δ ≥ 門檻，CI 下界 > 0 | **PROVEN** | 可進預設路徑；可對外宣稱與計價 |
| 0 < Δ < 門檻，CI 下界 > 0 | **MARGINAL** | 保持 flag 關閉；列為「特定 KB 選用」；不得作為主要賣點 |
| CI 跨 0 | **INCONCLUSIVE** | 補題數或重跑；**不得**當作 PASS 或 FAIL |
| Δ ≤ 0 | **NO VALUE** | 從預設路徑移除；模組定位需重新檢討（可能改為僅保留解析而不賣檢索） |

**禁止**：因為結果不如預期而調降門檻、更換較易的題目、或改用 mock。門檻調整只能在**看到結果之前**、且需記錄理由。

### 9.2 主要風險登記

| 風險 | 影響 | 緩解 |
|------|------|------|
| 黃金集人工標註無法完成（成本最高項） | 部分 CV-* 無法判定 | 分層漸進（Phase 0 Tier 0/1/2）：Tier 0 免標註即可判 RF-01；Tier 1 僅 4–6h；Tier 2 條件式 |
| PH-03 無真實 ACL 來源 | Enterprise Connect Pack 核心賣點無法證明 | **v1.4 定案採 BookStack**（§2.2，權限程式碼已驗證為活的）；備援 Confluence DC；建置完成前標 BLOCKED |
| 上游 connector 程式碼「看起來有」但實際是死的（S3 無解析、Nextcloud 解析函式零呼叫點） | 選錯來源浪費整段工期、產出無效證明 | **評估規則（v1.4 起強制）**：任何 connector 採用前必須驗證權限函式的呼叫點與寫入路徑，不得只看函式存在 |
| 合成掃描與真實掃描有落差 | RF-01 結論高估 | G-PARSE-SYN 結果必須經真實掃描驗證集（Z1-1）確認遷移；artifact 標 `corpus=synthetic_scan` |
| 重解析破壞既有 citation | 現有問答斷鏈 | 新 dataset 並行 + backup + 驗證後切換（見 Phase B） |
| LLM 產出變異大於效果量 | Wiki／GraphRAG 判定不穩 | 3 次重跑取中位數；全距 > 門檻判 INCONCLUSIVE |
| 三方 embedding 不一致 | 跨 provider 比較不公平 | 統一 `bge-m3` 或只比排序指標（§3.0e） |
| PipesHub `indexing=unhealthy` | 修好 token 仍搜不到東西 | Phase C 出口條件納入；先修再談 ACL |
| 舊閘門仍為綠、造成誤讀 | 對外宣稱過度 | `plan_progress_gate` 新增 `capability_value_gates` 區段，舊 PASS **不繼承**；§7 宣稱文案強制 |

### 9.3 `plan_progress_gate` 整合具體要求

不可只寫「新增區段」。實作需求：

1. 新增 `CV_GATES` 清單（gate id → artifact 檔名 → 必要欄位 → 判定鍵）。
2. artifact 缺檔、`status != PASS`、或 `corpus_snapshot_id` 與當前語料不符 → 記為 `false_green` 候選。
3. `--strict` 時，任一 CV gate 非 PASS 即整體 FAIL（與既有 checkbox 邏輯分列輸出，避免互相掩蓋）。
4. `PLAN_PROGRESS.md` 產出新增「能力價值」表格，欄位含判定（PROVEN／MARGINAL／INCONCLUSIVE／NO VALUE／BLOCKED）。
5. artifact 需記錄 `golden_tier`（0／1／2）與實際 n；Tier 1 小樣本得出的 PROVEN 必須在宣稱文案標註樣本規模，不得與 Tier 2 結果混用同一句宣稱。

---

## 10. 文件維護

- 每完成一個 CV-* 閘門：更新本節狀態表 + `artifacts/` +（可選）`PLAN_PROGRESS.md` 新區段。
- 現場設定變更（dataset layout、API key 輪替）必須可重跑腳本，禁止只改 UI 不留代碼／runbook。
- 與主計畫衝突時：**安全與 ACL fail-closed 優先**；增量不夠則關 flag，不開宣稱。

---

**本計畫的成功不是「又部署了三套系統」，而是：客戶在 Enclave 裡用到的每一項來自 RAGFlow／PipesHub／WeKnora 的能力，都能指出開關、指出產出、指出相對 baseline 的數字增益。**
