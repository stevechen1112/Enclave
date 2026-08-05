# ADR-009：Gateway 融合不變量（權威級／可引用性／域隔離）

**狀態**：提議（Proposed）  
**日期**：2026-08-03  
**決策者**：Enclave 技術團隊  
**關聯**：ADR-005、ADR-007、ADR-008、`docs/FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN.md`

---

## 背景

Chat 預設走 Gateway fan-out（document／wiki／graph／connector）。  
現場證據（2026-08-03，R14）：

- Canonical `/kb/search`：費用流程之後緊接兩張 **營業稅繳款書**（正確文件在庫）。  
- `chat/stream` sources：費用流程之後變成 **WeKnora** 片段（GRI Climate／Biodiversity 等），`title` 空、無可對使用者展示的內部檔名。  
- 模型因此回答「只有憑證類型、沒有檔名」——**檔在主索引，融合階段被擠掉**。

根因不是「WeKnora 不該存在」，而是 **缺少融合不變量**：跨 provider 分數裸比＋無引用資格過濾。

單純「盤點題關閉 WeKnora」是治標，換題或換域仍會再犯。

## 決策

**在 `ResultAggregator`／Gateway 出口引入版本化 `FusionPolicy`；所有進 chat context 與使用者可見 sources 的 hit 必須通過不變量。**

### 不變量（v1）

1. **可引用性（citation_ok）**  
   - Document／catalog／chunk：`provider` + `document_id` + 非空 `filename`（或同等 title）才可進答案。  
   - Compiled：必須能展示穩定 title，且 trace 含 `provider`；若宣稱源自某內部文件，必須帶可解析 `document_id`。  
   - `citation_ok=false` → 不得進入 `context_parts`／使用者 sources（可進 debug trace，並計數 `dropped_non_citable`）。

2. **權威級（authority_class）**  
   - `primary_document`：Enclave 主索引文件／chunk（含經 Facade 的 document adapter）。  
   - `compiled_knowledge`：Wiki／GraphRAG 等編譯產物。  
   - `external_context`：連接器／外部脈絡。  
   - 合併時先按權威級配額，再取分數；**禁止**跨 class 裸 RRF／min-max 後直接截斷當唯一規則。

3. **域隔離（query_domain，v1 枚舉）**  
   - `internal_records`：內部憑證、表單、合約掃描、入出境證件、稅務繳款等（分類器初版允許保守規則；可演進）。  
   - 當 domain=`internal_records` 且存在 ≥1 個 `primary_document` 命中時：  
     - compiled／external **不得**排在所有 primary 之前；  
     - 進入 context 的 primary 配額優先滿足（例如先填滿 primary 的 top_m，再附錄 compiled）。  
   - 其他 domain：維持輔助召回，但仍受可引用性約束。

4. **觀測**  
   - retrieval trace 必含：`fusion_policy_version`、`query_domain`、`dropped_non_citable`、`providers_called`。

### 明確不採用（v1）

- 依題號或題幹白名單關閉某 provider。  
- 全局預設關閉 WeKnora 作為「融合已修復」的宣稱。  
- 無 trace 的靜默丟棄（必須可計數、可測）。

## 理由

1. **對準真實故障模式**：R14 是融合事故，不是檢索完全找不到文件。  
2. **可回歸**：可構造「高分無檔名 compiled + 中分有檔名 document」單元測試，斷言 document 勝出。  
3. **與 ADR-005／007 一致**：compiled 仍可存在，但不得冒充或覆寫主文件真相。  
4. **防包裝治標**：關源能綠燈但不提升架構；不變量讓來源留下且受規矩約束。

## 約束

- FusionPolicy 變更必須升 `fusion_policy_version`，並重跑 FD-FUSION 閘門。  
- Chat 與 Gateway search 出口必須走同一 Policy（禁止 chat 一套、API 一套）。  
- 不得在 Policy 外再寫一層「R14 專用」過濾。

## 後果

- Aggregator 從「正規化＋去重＋截斷」擴為「資格過濾＋分級配額＋截斷」。  
- 部分 wiki／graph 高分雜訊會從使用者可見 sources 消失——屬預期。  
- 需新增 `eval_foundation_fusion_gate.py` 與單元測試。  
- domain 分類器初期會有漏網／誤傷；誤傷應偏向「多留 primary」，不可偏向「讓 compiled 蓋過」。

## 落地對應

- 計畫 Phase F3：`FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN.md`  
- 閘門：FD-FUSION  
