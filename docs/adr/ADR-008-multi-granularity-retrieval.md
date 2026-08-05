# ADR-008：多粒度檢索（Catalog + Chunk + Compiled）

**狀態**：提議（Proposed）  
**日期**：2026-08-03  
**決策者**：Enclave 技術團隊  
**關聯**：ADR-005、ADR-002、`docs/FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN.md`

---

## 背景

Enclave 現行問答主路徑幾乎只檢索 **chunk**（段落向量／關鍵字）。  
2026-08-03 答案正確性錯題顯示：

- 「列出財務憑證檔名」「入出境／人資各有哪些檔」需要的是 **文件集合**，不是段落內容相似度。  
- 用 chunk-RAG 硬答盤點題，會命中「如何定義憑證／請假應附文件」的政策段落，系統性答錯。  
- 只加 prompt 或 Agent `document_list`、卻不改 `RetrievalFacade`，等於主路徑仍然只有一種粒度。

ADR-005 要求「單一主索引」。本 ADR 不新增第四個外部向量庫，而是在 **Enclave 主索引內** 區分粒度。

## 決策

**RetrievalFacade 必須一等支援三種粒度；chat 預設路徑依查詢計劃選臂，不得只有 chunk。**

| 粒度 | 名稱 | 存放 | 回答什麼 |
|------|------|------|----------|
| `catalog` | 文件層 | Enclave DB 文件列＋可選文件級嵌入／關鍵字 | 有哪些檔、類型、狀態、檔名列表 |
| `chunk` | 段落層 | Enclave pgvector（現況主路徑） | 事實、條款、數值、引用原文 |
| `compiled` | 編譯層 | Wiki／Graph 投影（WeKnora 等） | 已編譯知識；受 ADR-005／007 與 FusionPolicy 約束 |

### 契約要求

1. `RetrievalFacade` 暴露明確 API（名稱可調整，語意不可少）：
   - `search_catalog(authz, query, filters, top_k) -> list[RetrievalHit]`
   - `search_chunks(...)`（現有 search）
   - `search`／`search_gateway` 的結果必須標 `granularity`
2. 每一 `RetrievalHit` 含：`granularity`、`provider`、`authority_class`、`document_id`、`filename`（catalog/chunk 必填）、`citation_ok` 前置欄位。  
3. HTTP：`/api/v1/kb/search` 支援 `granularity=catalog|chunk|auto`；預設 `chunk` 以保相容。  
4. Chat 組 context 時：
   - inventory／list_filenames 類計劃 → **必須**納入 catalog 臂結果（檔名列表），不得僅依賴 chunk 正文碰巧含檔名。  
   - fact 類 → chunk 為主；catalog 可作附錄。  
5. Catalog 不要求一開始就有完美自動分類；`genre` 可先規則，**標註失敗不得擋住入庫**。

## 理由

1. **物理基礎**：沒有文件層索引，盤點題在數學上就不該交給段落相似度。  
2. **與 ADR-005 一致**：仍是 Enclave 主索引，只是主索引有兩層（文件／段落）。  
3. **可測**：Catalog 閘門可直接斷言檔名集合，無需 LLM judge。  
4. **防假治本**：若只做 list API 而 Facade／chat 不呼叫，本 ADR 視為未落地。

## 約束

- 禁止以「在 SYSTEM_PROMPT 要求列出檔名」替代 catalog 臂。  
- 禁止 tombstone／failed／非 completed 文件預設進入 catalog 命中（除非 debug 模式）。  
- 禁止為通過評測對題號寫死檔名列表。  
- compiled 臂不得冒充 catalog（不可用 Wiki 標題假裝庫內掃描檔清單，除非 citation 追溯到同一 `document_id`）。

## 後果

- 需維護文件級索引與（可選）文件嵌入成本——通常遠低於第三份全文向量庫。  
- ChatOrchestrator 需能消費多粒度 hits（context assembly 變更）。  
- 評測新增 `eval_foundation_catalog_gate.py`。  
- 舊客戶端不傳 `granularity` 時行為不變（chunk）。

## 落地對應

- 計畫 Phase F2：`FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN.md`  
- 閘門：FD-CATALOG  
