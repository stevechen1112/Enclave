# Enclave 檢索與交付真治本計畫

**文件版本**：1.1  
**建立日期**：2026-08-03  
**狀態**：✅ F0–F4 完成並驗證（2026-08-03；FD-* 全 PASS）  
**關聯**：
- `docs/adr/ADR-008-multi-granularity-retrieval.md`
- `docs/adr/ADR-009-gateway-fusion-invariants.md`
- `docs/adr/ADR-010-scan-parse-delivery-invariant.md`
- `docs/adr/ADR-005-single-primary-index.md`（仍有效；本計畫擴充其「主索引」語意，不推翻）
- `docs/DEVELOPMENT_PLAN_TRIPLE_INJECTION.md`（Control Plane 主計畫；本文件不重複其 checkbox）
- `docs/CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md`（能力啟用／消融；本文件專注架構契約）
- 現場證據：`artifacts/answer_correctness_last_run.json`、2026-08-03 錯題根因（R12／R14／R15／R19）

---

## 0. 為什麼需要這份文件

### 0.1 問題不是「那幾題沒過」

答案正確性驗收中，事實題（統一編號、稅額、拒答）已可過；失敗集中在：

| 題型 | 現象 | 不是根因 |
|------|------|----------|
| 庫內檔案盤點／分類 | 答成「政策如何定義憑證／人資」 | 單純 LLM 笨 |
| 多源 chat | WeKnora 無檔名片段擠掉營業稅繳款書 | 關 WeKnora 就能變強 |
| 複合盤點問句 | 「入出境＋人資」漏掉 e-Arrival | 多寫幾個 synonym |
| 跨語條款對照 | ETI 緬甸文已在 chunk，仍拒答 | prompt 說「可以翻譯」 |

這些暴露的是 **索引粒度、融合契約、入庫不變量** 不足——屬架構底座，不是答題特判。

### 0.2 本文件唯一目標

讓下列三項成為 Enclave **可執行、可測試、可回歸** 的產品不變量：

1. **入庫交付不變量**（語料底座）  
2. **多粒度檢索契約**：Catalog（文件）＋ Chunk（段落）寫進 `RetrievalFacade`  
3. **Gateway 融合不變量**：權威級／適用域／可引用性，禁止雜訊擠掉主索引命中  

**不做**：intent 正則特判、為單一題改 prompt、預設關閉 sidecar 當「修法」。

### 0.3 治本 vs 包裝治標（驗收尺）

施工完成後，拿掉所有「題型 if／特殊 prompt／暫時關源」仍須成立：

| 測試 | 通過條件 |
|------|----------|
| 新盤點題（訓練時未見過的檔名集合） | Catalog 路徑能列出正確檔名，不必靠 chunk 裡碰巧出現檔名 |
| 內部憑證／表單類查詢 | chat gateway 路徑下，WeKnora／graph 不得以無 `document_id`+檔名的結果擠出 Enclave document 命中 |
| 掃描 PDF | `native/text_fallback` 不得 `completed`；髒 OCR 必須救援或 `failed` |
| 回歸 | 對應 `artifacts/foundation_*_last_run.json` 閘門 PASS |

任一條靠特判才過 → **視為未完成治本**，不得勾選本計畫出口。

---

## 1. 現況基線（2026-08-03）

### 1.1 已有／缺口

| 層 | 現況 | 缺口 |
|----|------|------|
| 入庫 | `SCAN_PARSE_STRICT`、雲端 OCR 髒文本觸發已落地；部分舊件仍 `text_fallback` completed；nueip 因 poppler 失敗 | 不變量未全面 ADR 化；環境依賴未進交付閘門 |
| 索引 | 幾乎只有 chunk 向量／關鍵字；文件 metadata 未當一等檢索單位 | 無 Catalog search 契約 |
| 融合 | `ResultAggregator` 正規化＋去重＋截斷；跨 provider 分數可比性弱 | 無權威級／適用域／可引用性過濾 |
| Chat | `retrieve → top5 context → SYSTEM_PROMPT`；無文件盤點臂 | 盤點題被迫用段落相似度硬湊 |
| 評測 | 答案 span／retrieval Hit@K；**無**「融合不污染」「Catalog 盤點」閘門 | 綠燈不等於架構不變壞 |

### 1.2 關鍵現場證據（摘要）

- R14：`/kb/search` top 含兩張營業稅繳款書；`chat/stream` gateway sources 被 WeKnora（GRI 等、title 空）取代 → **融合事故**。  
- R15：單獨查「e-Arrival」命中；複合「入出境相關文件與人資…」top-8 零 Arrival → **僅有 chunk 相似度、無 Catalog／多臂**。  
- R12：`000_nueip 合約(1).pdf` `failed`（poppler）→ **交付底座破洞**。  
- R19：ETI chunk 已召回 → **非本計畫 P0**（跨語正規化列 P2，見 §6）。

---

## 2. 架構決策（契約層）

詳見 ADR-008／009／010。此處只列施工必須遵守的接口級約束。

### 2.1 三粒度（與 ADR-005 相容）

```text
Query
  → QueryPlan（可先極簡：explicit mode 或規則；禁止為過關寫死題號）
  → RetrievalFacade
       ├─ catalog.search   → DocumentHit[]   （文件層）
       ├─ chunk.search     → ChunkHit[]      （段落層；現有主路徑）
       └─ compiled.search  → CompiledHit[]   （Wiki／Graph；輔助，受 ADR-005／007 約束）
  → FusionPolicy.apply（ADR-009）
  → ContextAssembly（依計劃選臂；盤點題以 Catalog 為主）
  → Answer
```

- **主索引仍是 Enclave**（ADR-005）：Catalog 與 Chunk 都建在 Enclave 控制面／pgvector／DB，不新建第三份「平行真相」。  
- Compiled（WeKnora）維持輔助；**不得**在禁止域覆寫 Document 命中。

### 2.2 統一命中物件（最小欄位）

所有進答案組裝的 hit 必須能投影為：

```text
RetrievalHit:
  granularity: catalog | chunk | compiled
  provider: enclave | ragflow | weknora | pipeshub | ...
  authority_class: primary_document | compiled_knowledge | external_context
  document_id: UUID | null
  filename: str | null          # catalog/chunk 必填；compiled 若無可追溯文件則 null
  chunk_index: int | null
  score: float
  content_or_summary: str
  citation_ok: bool             # FusionPolicy 計算結果
```

`citation_ok=false` 的 hit：**不得**進入 chat context_parts，也不得出現在使用者可見 sources（可留在 debug trace）。

### 2.3 FusionPolicy 最小不變量（ADR-009）

1. **可引用性**：進答案的 hit 必須 `citation_ok`（至少 `provider` + 可展示標題；document 臂還需 `document_id` + `filename`）。  
2. **域隔離（初版枚舉）**：查詢被標為 `internal_records`（憑證／表單／合約掃描／入出境證件等）時，`authority_class=compiled_knowledge|external_context` **不得**排在任何 `primary_document` 命中之前；若 primary 命中數 ≥ 1，compiled 最多附錄且需可追溯。  
3. **分數不可跨 provider 裸比**：跨源必須先 provider 內排序，再按權威級配額合併（初版可用配額，不必上複雜學習排序）。  
4. **觀測**：每次 chat retrieval trace 記錄 `providers_called`、`dropped_non_citable`、`fusion_policy_version`。

### 2.4 入庫交付不變量（ADR-010）

- 掃描／DeepDOC 路由：`native/text_fallback` ⇒ 不得 `status=completed`。  
- 髒 OCR／空產能：雲端救援或 `failed`，禁止靜默成功。  
- 執行環境缺依賴（如 poppler）⇒ **failed + 明確 error_message**，不得標 completed。  
- 標籤誠信：`parse_engine`／`ocr_used` 與上游一致（既有 label integrity 延續）。

---

## 3. 明確不做（防包裝治標）

| 禁止 | 原因 |
|------|------|
| 依題號（R14…）或題幹正則切 WeKnora | 包裝治標；換題即失效 |
| 只加 `/documents?q=` API 卻不改 Facade／chat 預設路徑 | Catalog 未成為檢索契約 |
| Prompt「請列出檔名」但 context 仍只有 chunk | 無物理基礎 |
| 預設全局關閉 WeKnora 宣稱「融合已修好」 | 逃避契約 |
| 降低黃金集難度或改 mock provider 過閘門 | 假綠 |
| 本階段大做 Agent-only 工具當唯一解 | 客戶主路徑是 chat；治本須改 Facade |

---

## 4. 分期施工

### Phase F0 — 契約凍結與測量（文件＋閘門骨架）✅ 完成（2026-08-03）

- [x] 本計畫 + ADR-008／009／010 落盤  
- [x] `scripts/eval_foundation_fusion_gate.py` 骨架：重放 R14 類查詢，斷言 gateway 路徑下營業稅檔名不可被無檔名 compiled 擠出 top context  
- [x] `scripts/eval_foundation_catalog_gate.py` 骨架：固定盤點題，斷言 Catalog 臂檔名集合  
- [x] `artifacts/foundation_*_last_run.json` schema 定案（見 §5.1）  
- [x] `docs/OPEN_GATES.md` 掛上本計畫入口  

**出口**：閘門可跑（允許 FAIL）；契約審閱通過。✅

**F0 首跑結果（2026-08-03，預期 FAIL，證明閘門抓得到真問題）**：

| 閘門 | 狀態 | 抓到的契約違反 |
|------|------|----------------|
| FD-CATALOG | FAIL（2/2） | `catalog_arm_missing`：`granularity=catalog` 被靜默吞掉，無文件層檢索臂 |
| FD-FUSION | FAIL（3/3） | `non_citable_source_visible`（2 筆 WeKnora 無檔名 source 可見——R14 事故現場重現）、`primary_document_displaced`（營業稅繳款書被擠出）、`fusion_observability_missing`（缺 `dropped_non_citable`／`fusion_policy_version`） |

### Phase F1 — 入庫交付不變量收斂（ADR-010）✅ 完成（2026-08-03）

- [x] Worker／映像保証掃描依賴（poppler／pdf2image 等）或明確 fail 訊息標準化  
  - 現行 Dockerfile 已含 `poppler-utils`／`tesseract-ocr(-chi-tra)`；CI `docker-build` 新增映像內依賴斷言（缺 pdftoppm／tesseract／pdf2image 即建置失敗）  
  - **結構修復**：`parse_pipeline` 原生降級的 `ValueError`（品質閘門，如缺 poppler）不再繞過雲端 OCR 救援——RAGFlow 0-chunk fallback 與 native 路徑都先給救援機會，救援無效才以 `ScanParseDeliveryError`（可行動訊息）failed  
- [x] 存量 `completed + text_fallback`／`failed` 可重跑清冊腳本：`scripts/inventory_delivery_status.py`（FD-DELIVER 閘門，產出 `artifacts/foundation_delivery_last_run.json`）  
- [x] nueip 等失敗件重入庫：`scripts/reingest_delivery_failures.py`（uploads→黃金集雜湊比對取回源檔；先清舊 chunks 防 text_fallback 殘留污染）——7 份 completed（nueip／001／007／008／009／014／工作規則 23 chunks）、4 份測試殘留（a.pdf×2／employee_handbook／spec，假雜湊無來源）標 failed＋可行動訊息  
- [x] `tests/test_scan_parse_delivery.py` 維持綠（11/11）；新增 3 個環境缺依賴案例（救援不被繞過／無救援時 actionable failed／native 路徑 ValueError 進交付閘門）  
- [x] label integrity 與 delivery 閘門納入 preflight：Makefile `foundation-gates` 目標；兩測試檔本就在 CI `backend-test`；動態 label integrity 重跑 PASS（42 件檢查、0 違規）  

**出口**：黃金掃描集 0×（completed∧text_fallback）✅；失敗件有可行動錯誤 ✅。  
**FD-DELIVER 首跑 FAIL（10 違規）→ 收斂後 PASS（26 活動件：22 ok、4 failed_actionable 皆測試殘留）。**

### Phase F2 — Catalog 索引與 Facade 契約（ADR-008）✅ 完成（2026-08-03）

- [x] Document catalog 資料模型：`documents` 表新增 `genre` 欄（migration `f2_documents_genre_001`）；`document_id, filename, status, genre, content_hash, tombstoned_at` 齊備  
- [x] `genre` 初版：`app/services/genre_tagger.py` 規則標註（contract／voucher／manual／travel／policy／form／report／other）；入庫 hook 於 `process_document_task` 標註（失敗僅告警不擋入庫）；存量以 `scripts/backfill_genre.py` 回填 26 件  
- [x] `RetrievalFacade.search_catalog(...)` + 統一 `RetrievalHit` 投影（`app/services/catalog_retrieval.py`）  
- [x] `/api/v1/kb/search` 支援 `granularity=catalog|chunk|auto`（預設 chunk 保相容；auto 以 `is_inventory_query` 極簡規則選臂）  
- [x] Chat：`retrieve_context` 偵測盤點意圖即呼叫 catalog 臂，檔名清單以【庫內文件清單】進 context_parts、catalog sources 可引用、retrieval event 帶 `arms`；catalog 失敗不阻斷 chunk 主路徑  
- [x] 契約測試：`tests/test_chat_catalog_arm.py`（4/4：盤點進 context／非盤點不呼叫／catalog 失敗降級／無 chunk 命中仍可答有哪些檔）  

**出口**：`eval_foundation_catalog_gate.py --with-chat` PASS（2/2；chat retrieval event `arms=["catalog","chunk"]`，檔名召回含營業稅繳款書／補印發票切結書／e-Arrival／nueip／由你人資MOU）✅。

### Phase F3 — Gateway FusionPolicy（ADR-009）✅ 完成（2026-08-03）

- [x] `FusionPolicy` 模組（`app/gateway/fusion_policy.py`，`FUSION_POLICY_VERSION="1.0"`）；router 於後授權過濾後呼叫之  
- [x] 丟棄 `citation_ok=false`（無檔名／無 title；primary 另需 document_id），計數 `dropped_non_citable`，不靜默  
- [x] `internal_records` 域配額合併：存在 primary 命中時 primary 優先填滿，compiled/external 僅附錄；一般域維持分數序  
- [x] retrieval trace 欄位齊備：`AuditTrail` 新增 `fusion_policy_version`／`query_domain`／`dropped_non_citable`，chat retrieval event 透出；canonical fallback 路徑走同一政策過濾  
- [x] `eval_foundation_fusion_gate.py` PASS（3/3：R14 重放＋盤點重放＋未見過的補印發票切結書查詢；`providers_called` 仍含 wiki/graph/connector——非關源假綠）  
- [x] 單元測試：`tests/test_fusion_policy.py`（13 案，含人造 WeKnora 高分無檔名 hit 不得贏過 Enclave document hit）  

**出口**：chat gateway 與 kb/search 在融合不變量上一致 ✅；FD-FUSION PASS（`non_citable_visible=0`，營業稅繳款書／補印發票切結書均在 sources）✅。

### Phase F4 — 編排與跨語（F2／F3 PASS 後；2026-08-03 開工）

- [x] QueryPlan 結構化（inventory／fact／compare／translate／multi_hop）進 control plane  
  - `app/services/query_plan.py`；`is_inventory_query` 單一事實來源  
  - chat／kb `auto` 走 `build_query_plan`；複合盤點拆 `sub_queries`  
  - retrieval event 帶 `query_plan`（plan_version／intent／arms／sub_queries）  
  - 測試：`tests/test_query_plan.py`、`tests/test_chat_catalog_arm.py`  
- [x] 跨語：入庫後條款對照投影（DocumentArtifact `clause_projection`），非 prompt 猜測  
  - `app/services/clause_projection.py`＋`scripts/build_clause_projections.py`  
  - translate 意圖讀投影進 context；入庫 hook 非阻塞  
  - 測試：`tests/test_clause_projection.py`  
- [x] 線上 ETI 投影建置＋translate 主路徑驗證（2026-08-03）  
  - `build_clause_projections.py --filename-substr ETI` → 32 條款  
  - 線上 chat「ETI Base Code 條款編號與標題對照」：`intent=translate`、`clause_projections=1`、答案含條號＋中英標題  
- [x] 與 WeKnora 編譯節奏對接（ADR-007 邊界不變）  
  - `sync_clause_projection_to_wiki`：Enclave Wiki `page_type=comparison`／`provider=enclave`（非 Neo4j 雙寫）  
  - 有 KB 且 `WEKNORA_ENABLED` 時另發 `wiki/compiled` outbox 觸發 sidecar 重編譯  
  - 存量同步：`scripts/sync_existing_clause_wikis.py`  
- [x] 正式閘門腳本＋掛 `plan_progress_gate`  
  - `eval_foundation_queryplan_gate.py` → FD-QUERYPLAN  
  - `eval_foundation_clause_gate.py` → FD-CLAUSE（DB 投影＋Wiki 同步＋chat）  
  - `FOUNDATION_GATES` 區段納入 `plan_progress_gate.py`；`make foundation-gates` 含全部 FD-*  
  - R19 `span_contains` 改以條款投影為 ground truth  

**出口**：F0–F4 完成；全部 FD-* 閘門可重跑且 PASS 後，可宣稱本計畫架構契約已落地。✅

---

## 5. 閘門與產物

| 閘門 ID | 腳本 | Artifact | 對應 |
|---------|------|----------|------|
| FD-DELIVER | `inventory_delivery_status.py` | `artifacts/foundation_delivery_last_run.json` | F1 |
| FD-CATALOG | `eval_foundation_catalog_gate.py` | `artifacts/foundation_catalog_last_run.json` | F2 |
| FD-FUSION | `eval_foundation_fusion_gate.py` | `artifacts/foundation_fusion_last_run.json` | F3 |
| FD-QUERYPLAN | `eval_foundation_queryplan_gate.py` | `artifacts/foundation_queryplan_last_run.json` | F4 |
| FD-CLAUSE | `eval_foundation_clause_gate.py` | `artifacts/foundation_clause_last_run.json` | F4 |

閘門必須：

1. 可重跑、無網路 mock sidecar（允許本機 stack）。  
2. **禁止**讀題號白名單當唯一通過條件（可用固定查詢字串，但不可 `if qid=="R14"`）。  
3. 失敗時指出違反哪條契約（delivery／catalog／fusion）。

### 5.1 Artifact Schema（`foundation_*_last_run.json`，schema_version=1，2026-08-03 定案）

```json
{
  "gate": "FD-DELIVER | FD-CATALOG | FD-FUSION",
  "schema_version": 1,
  "generated_at": "YYYY-MM-DDTHH:MM:SS",
  "base_url": "http://localhost:8001",
  "method": "量測方法一句話（供審閱者判讀）",
  "status": "PASS | FAIL | BLOCKED",
  "contract_violations": ["<contract>: <細節>"],
  "elapsed_s": 0.0,
  "summary": {"total": 0, "pass": 0, "fail": 0, "blocked": 0},
  "cases": [
    {
      "id": "固定案例 id（非黃金題號）",
      "query": "固定查詢字串",
      "expectation": {"...": "預期（檔名子串／source 子串）"},
      "verdict": "pass | fail | blocked",
      "violations": ["..."],
      "observed": {"...": "實際觀測（標題列表／granularity echo／providers_called）"}
    }
  ]
}
```

規則：

- `status=BLOCKED` 僅用於 stack 不可達／登入失敗；**不得**用 BLOCKED 掩蓋契約違反。
- `contract_violations` 的字首必須是契約條目 id（如 `catalog_arm_missing`、`non_citable_source_visible`、`primary_document_displaced`、`fusion_observability_missing`、`delivery_false_completed`），供 `plan_progress_gate` 與人工審閱分類。
- 案例 `id` 描述情境（`replay_tax_voucher_fact`），不引用 R 題號；查詢字串固定寫在腳本內。

---

## 6. 與既有計畫的關係

| 計畫 | 關係 |
|------|------|
| Triple Injection 主計畫 | 本文件補 Phase 5 檢索底座的下一層契約；不重開 Control Plane |
| 能力啟用／消融 | 仍管「上游能力有沒有增量」；本文件管「Enclave 主路徑會不會被雜訊與錯粒度打穿」 |
| ADR-005 | 維持單一主索引；Catalog 是主索引的**文件層**，不是第四個向量庫 |
| UI／Wiki 編輯 | 正交；Wiki 屬 compiled 臂，受 FusionPolicy 約束 |

---

## 7. 成功定義（產品語言）

完成 F1–F3 後，Enclave 應能誠實宣稱：

1. 掃描／OCR **不會**靜默假完成。  
2. 問答主路徑具備 **文件層與段落層** 兩種合法檢索，且盤點題走文件層。  
3. 多源召回受 **可引用性與權威域** 約束，輔助知識不能默默蓋過內部主文件命中。  

不得宣稱：

- 「已支援任意複雜 Agent 推理」  
- 「WeKnora／Graph 已證明增量故預設全開」  
- 「跨語法律條款自動對照已完成」（除非 F4 閘門 PASS）

---

## 8. 建議工期（粗估）

| Phase | 粗估 | 依賴 |
|-------|------|------|
| F0 | 0.5–1 日 | 本文 |
| F1 | 1–2 日 | 映像／存量清冊 |
| F2 | 3–5 日 | F0；genre 可先規則 |
| F3 | 2–4 日 | F2 的 Hit 模型為佳，可並行骨架 |
| F4 | 另估 | F2／F3 PASS 後 |

---

## 9. 開工指令（代理人）

```bash
make foundation-gates
# 或：
python scripts/inventory_delivery_status.py
python scripts/eval_foundation_catalog_gate.py --with-chat
python scripts/eval_foundation_fusion_gate.py
python scripts/eval_foundation_queryplan_gate.py
python scripts/eval_foundation_clause_gate.py
python -m pytest tests/test_query_plan.py tests/test_fusion_policy.py tests/test_scan_parse_delivery.py tests/test_clause_projection.py tests/test_chat_catalog_arm.py -q
python scripts/eval_answer_correctness.py
```

施工順序：**F0 → F1 → F2 → F3 → F4**（已全部完成）。  
FD-* 狀態以 `artifacts/foundation_*_last_run.json` 與 `OPEN_GATES.md` 為準。
