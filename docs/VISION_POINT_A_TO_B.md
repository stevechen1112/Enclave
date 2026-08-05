# Enclave 願景路線圖：Point A → Point B

**文件版本**：1.5  
**建立日期**：2026-08-03  
**修訂**：1.5 — 植入 source-grounded 逐字溯源稽核層（移植自 UniHR 比較實驗，含 derived 論點擴充）；shadow 模式上線  
**定位**：長期願景與路線總綱（非單一 sprint 計畫）  
**關聯**：
- `docs/FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN.md`（地基；F0–F4 ✅）
- `docs/adr/ADR-008/009/010`（架構契約）
- `docs/DEVELOPMENT_PLAN_TRIPLE_INJECTION.md`（Control Plane 主計畫）
- `docs/CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md`（能力啟用／消融）

---

## 完成度總覽（2026-08-03 驗證）

| Phase | 內容 | 完成度 | 證據 |
|-------|------|--------|------|
| **1 地基** | 入庫／Catalog／融合／F4 閘門 | **~100%** | FD-* 五閘門 PASS；盲測抓出 RAGFlow chunk 同步競態並修復 |
| **2 編排大腦** | QueryPlan／ToolRouter／MultiStep／Trace／拒答 | **~92%** | 模組落地；FD-QUERYPLAN PASS；檔名導向 scoped 檢索＋document head 不變式上線 |
| **3 跨語／編譯** | 條款投影＋Wiki 同步＋ETI | **~80%** | FD-CLAUSE PASS；R19 pass；通用多語仍可擴 |
| **4 驗收文化** | 黃金集／對抗集／盲測集／重跑 | **~92%** | 主集 128＋盲測集 27（8 份未見文件）；對抗集 8/8 PASS |
| **5 能力上限** | rerank／強 LLM／投影就位 | **~85%** | `VISION-CEILING` PASS；Voyage rerank-2.5 接入；三模型消融完成 |

**整體朝 Point B**：約 **75–85%**（架構與驗收骨架已齊；**不可再以 Z2 27/27 單獨宣稱 Point B 已證明**。2026-08-05 Blind Z3 **67/85**、Blind Z4 **39/50** 為未見語料一次跑分；暴露金額過拒、表格金額與短客戶名檢索缺口）。

### 最新驗收數字

| 閘門／評測 | 結果 | 備註 |
|------------|------|------|
| FD-DELIVER／CATALOG／FUSION／QUERYPLAN／CLAUSE | PASS | 2026-08-03 |
| VISION-ADV 對抗集 | **8/8 PASS** | |
| VISION-CEILING | PASS | |
| 答案正確性（主集 40＋展開） | 曾 **128/128** | 題庫易飽和；非泛化鐵證 |
| **Z2 盲測（8 份、27 題）** | **27/27** | **方法弱**：多「根據文件《檔名》」+ span；修洞後同集滿分 **不可當 Point B** |
| **Blind Z3（55 檔 hold-out、85 題）** | **67/85 pass**（3 fail／15 review） | 2026-08-05；見 `artifacts/blind_z3/BASELINE_TRIAGE.md`；題幹凍結後一次跑分 |
| **Blind Z4（40 檔 hold-out、50 題）** | **39/50 pass**（5 fail／6 review） | 2026-08-05；GT＝入庫全文；見 `artifacts/blind_z4/BASELINE_TRIAGE.md` |
| 定向回歸探針 | 歷史 6/6 | 非盲測取代 |

### 盲測（2026-08-03）：Z2 — 8 份未見文件 × 27 題（歷史紀錄）

- 文件來源：本機隨機挑選（掃描 PDF／數位 PDF／DOCX／手冊），經 `/api/v1/documents/upload` 真實上傳入庫。
- 題庫：`testdata/golden/z2_blind_questions.yaml`；ground truth 由 `artifacts/_blind_extract.py` 自原始檔獨立抽取（不受系統解析影響）。
- 最終結果 **27/27 = 100%**；過程抓出並修復 6 項架構缺陷（見下節）。
- **2026-08-05 降級**：此結果保留為「修洞迴圈證據」，**不得對外表述為 Point B 已達成**；正式盲測基線改看 Blind Z3。

### 盲測驅動的架構修復（治本）

| # | 缺陷 | 修復 |
|---|------|------|
| 1 | RAGFlow chunk 同步競態：chunks 非空即提前收斂，大 PDF 只同步 2/25 chunks 仍標 completed（假綠） | `ragflow_http.get_parse_result` 須 `run_status=DONE` 才收 chunks，並分頁取全量 |
| 2 | `kb_retrieval` 的 `filter_dict` 對 JSON 欄位用 `.astext` 觸發 `AttributeError`，scoped 過濾靜默失效退回廣搜 | 改用 `func.json_extract_path_text`（JSON/JSONB 通用） |
| 3 | `_UNANSWERABLE_HINTS` 以年份（2028/2030）當拒答觸發，對抗集過擬合，誤殺可答題 | 移除年份啟發式；有 `mentioned_documents` 時不短路拒答，交 LLM 依證據判斷 |
| 4 | scoped 查詢把 `《檔名》` 併入 embedding，稀釋語意 | `_run_scoped_chunk` 先剝離檔名再送檢索；fallback 廣搜同 |
| 5 | `chat_orchestrator` 上下文硬切 `[:5]`，scoped 多取無效 | 檔名導向題自適應上限 12 chunks |
| 6 | scoped 命中缺文件頭（標題／表頭），E073 類題被拒答 | document head 不變式：`facade.get_document_head()` 前置首 2 chunks |

**已知潛在缺陷（已修復）**：~~`kb_retrieval._cache_key` 未含 `filter_dict`~~ → 2026-08-03 深夜已修：cache key 納入規範化 `filter_dict`（排序 JSON），並補兩個契約測試（scoped／非 scoped 不得共用條目、寫讀不交叉命中）。

### 2026-08-03 深夜：E010 根因更正＋FD-DELIVER 對帳強化

1. **E010 真根因＝入庫不完整**（非語意排序）：active 文件僅 1 chunk（競態修復前的舊入庫），重新入庫後 3 chunks＋雲端 OCR 乾淨文本，E010 通過。
2. **FD-DELIVER 新增 RAGFlow 對帳**：completed 且無雲端 OCR 救援的文件，Enclave chunk 文本總字數不得低於 RAGFlow 端 80%（比字數而非 chunk 數——Enclave 會接合後重新切塊，chunk 數差異是設計使然；首版以 chunk 數比對產生 5 個假陽性後修正）。
3. **cache key 納入 filter_dict**＋契約測試 ×2（tests/test_outbox_cache_gates.py）。
4. **ground truth 目視校正**：E003「陳有竹」→「陳宥竹」（直接檢視原掃描圖，舊 OCR 誤讀；雲端 OCR 正確）；R04 span「立切結書人」→「切結書人」（合理措辭變體，E083 保留精確標籤驗證）。
5. **e2e 測試殘留清理**：25 筆測試租戶（WikiEval／Tenant A/B／VSlice／Lineage）文件 tombstone，FD-DELIVER 恢復 PASS（29/29 ok）。注意：對 dev DB 跑 e2e 會污染閘門，後續應讓 e2e 自清或隔離 DB。

### 模型消融（同條件：Voyage rerank＋同一 span 正規化）

| 模型 | 通過率 | 失敗題 |
|---|---|---|
| gpt-5.6-luna | 127/128 (99.2%) | E010 |
| gpt-5.6-terra | 126/128 (98.4%) | E010, E073 |
| gpt-5.6-sol | 127/128 (99.2%) | E010 |

結論：題庫已飽和、無法區分模型等級；瓶頸在架構不在模型。

**2026-08-04 定案（盲測對決後）**：以唯一有分辨力的題庫（盲測 27＋對抗 8，系統未見過的文件）讓三模型對決：

| 模型 | 盲測 27 | 對抗 8 | 溯源稽核全通過率（shadow） |
|---|---|---|---|
| gpt-5.6-sol | 27/27 | 8/8 | 74.8%（strict，後以 derived 收斂） |
| gpt-5.6-luna | **27/27** | **8/8** | — |
| gpt-5.6-terra | **27/27** | **8/8** | 81%（26/32） |

三模型在有分辨力的考卷上依然平手 → **主模型改定案 gpt-5.6-luna**（最便宜；品質無實測差異）。**gpt-5.6-sol 完全退場，任何路徑不再使用**；備用／升級順序為 Luna → **gpt-5.6-terra**（enforce 重生成、高難度多步意圖）。

~~E010 根因為檢索未浮出「人易科技」chunk（角色型問題語意排序弱），待 party-role artifact 解~~
**2026-08-03 深夜更正**：上述診斷有誤。E010 真實根因是**入庫不完整**——active 文件列只有 1 個 chunk（RAGFlow 同步競態修復前的舊入庫殘留），人易科技根本不在索引裡。以修復後程式重新入庫（3 chunks＋雲端 OCR 乾淨文本）後 E010 即通過，**不需要 party-role artifact**。教訓：檢索排序問題與入庫完整性問題必須先用 DB 證據區分，不能只看 LLM 輸出推論。

### 2026-08-04：Source-Grounded 逐字溯源稽核層（移植自 UniHR 比較實驗）

**動機**：UniHR 對考實測證明其「每條論點必須逐字節錄自檢索片段、程式化子字串驗證」機制是其防幻覺底線的支柱（拒答紀律 4/5、LLM 斷線全拒答不幻覺）。Enclave 殘餘失敗模式（E021 類：LLM 從上下文挑看似合理但錯誤的句子）正是此機制的解藥。

**實作**（pp/services/source_verifier.py＋chat_orchestrator.stream_answer 稽核層）：

- 生成之後、輸出之前的稽核：稽核 LLM 把回答拆成論點，每條附逐字 source_quote，程式化正規化子字串比對檢索片段；無法溯源者視為幻覺。
- **超越 UniHR 版的擴充**：derived 推導論點型別——民國/西元換算、百分比乘算、跨句組合等正確但非逐字的推導，要求列出逐字 asis_quotes 具結，避免誤殺合理推導（shadow 實測抓出 3 類假陽性後新增）。
- Feature flag：SOURCE_VERIFY_MODE=off/shadow/enforce；稽核預設走內部 LLM（SOURCE_VERIFY_MODEL=qwen3.6:35b，本地 Ollama 零邊際成本），失敗回退主 LLM。
- enforce 模式：緩衝→稽核→不通過則約束式重生成一次→再失敗則只輸出已驗證重點的誠實回答。
- 穩健性：Ollama 思考型模型 	hink:false＋空回應/截斷 JSON 自動 retry（max_tokens 倍增）；稽核任何異常降級不影響主回答。

**Shadow 實測（盲測 27 題）**：回答輸出零影響（27/27 仍 100%）；稽核覆蓋率 27/27 無 llm 故障；初版 strict verbatim 7 題有未溯源論點，逐題分析全為「正確推導被誤殺」→ derived 型別後收斂至 1 題殘餘假陽性（OCR 雜訊引述）。

**Shadow 全量回歸（2026-08-04）**：

| 項目 | 結果 |
|---|---|
| 主集 40 題（shadow） | 40/40 pass，輸出零影響 |
| 主集展開 88 題（shadow） | 87/88 pass；E035 單題重跑 pass（確認為 LLM 措辭變異，非稽核層回歸） |
| 稽核呼叫可靠性 | 131 次驗證 0 故障（thinking 預算／截斷 retry 全數生效） |
| 全論點逐字溯源率 | 98/131＝74.8%（strict）；未通過 33 題抽樣 12 條人工分類：**0 條真幻覺**，全部為正確但非逐字的表述（欄位對應 5、摘要改寫 2、推導 1、後設觀察 2、OCR 雜訊 2）→ 已擴充 derived 型別覆蓋，欄位對應類複測 4/4 通過 |
| enforce 冒煙 | 可答題一次通過輸出（含 OCR 矛盾主動標註）；對抗題誠實拒答；兩次皆首輪通過稽核 |

**邊界（誠實聲明）**：此層保證「回答忠實於檢索到的證據」，不保證「檢索到的是對的證據」——後者由 QueryPlan／scoped 檢索／交付閘門負責，兩道牆互補。enforce 上線時機待主集 128 題 shadow 數據確認誤殺率後決定。


### 2026-08-03 黃金題庫治本整備

1. 12 份 `z1_scan_annotations` 依 DB OCR 全文重標（原截圖標註 67 欄中 40 欄有誤）
2. `build_golden_from_annotations.py` 自檢閘門：expected 須存在於 OCR 全文，違規拒絕產題
3. 題幹自然化（`label` 欄位）；`span`／`ocr_surface`／`allow_absent` 語義
4. 檔名導向檢索：`QueryPlan.mentioned_documents`＋`_run_scoped_chunk`（修 E073–E079 檢索錯檔）
5. span 正規化：補零日期、期間範圍（含「至」）、千分位、前導零、正字法折疊（計畫≡計劃、臺≡台）
6. 生成層格式契約：SYSTEM_PROMPT 第 9 條（【檔名】首行通常為標題）

---

## 與 `CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md` 的差異（必讀）

| | 能力啟用／消融計畫（CAPABILITY） | 本願景＋FOUNDATION |
|--|--|--|
| **問的是** | 「sidecar 能力包有沒有比關掉更好？」 | 「亂丟文件、亂問時，正確性是否由架構撐住？」 |
| **證據** | 消融 Δ | 契約閘門 FD-*／VISION-* |
| **關係** | **互補** | CAPABILITY 證增量；VISION 證主幹不被打穿 |

---

## 0. 目標定義（Point B）

> **Enclave 變成一個敢讓客戶亂丟文件、亂問問題的產品**——上傳各種合約、掃描、表單、手冊之後，AI 問答的正確性、穩定性、可解釋性是**架構撐住的**，不是靠 prompt 或運氣。

成本不設限；可對外搜尋更好方案。

---

## 1–2. Point A → 路線（已執行）

```text
Point A
  ├─ Phase 1 地基 ✅（FOUNDATION F0–F4）
  ├─ Phase 2 編排 ✅ 核心（MultiStepOrchestrator / ToolRouter / TraceRecorder / refusal）
  ├─ Phase 3 跨語 ✅ 核心（clause_projection + Wiki sync；WeKnora 不搶位）
  ├─ Phase 4 驗收 ✅ 骨架（40+67 題、對抗集、可重跑腳本）
  └─ Phase 5 上限 ✅ 就位盤點（rerank／LLM／投影；深化消融待題型驅動）
```

---

## 3. Phase 1：地基 — ✅

FD-DELIVER／CATALOG／FUSION 全 PASS。詳見 FOUNDATION 計畫。

---

## 4. Phase 2：問答編排 — ✅ 核心完成

| 元件 | 狀態 | 路徑 |
|------|------|------|
| QueryPlan | ✅ v1.1（含 unanswerable） | `app/services/query_plan.py` |
| ToolRouter | ✅ | `app/services/tool_router.py` |
| MultiStepOrchestrator | ✅ | `app/services/multi_step_orchestrator.py` |
| TraceRecorder | ✅ | `app/services/trace_recorder.py` |
| 解釋式拒答 | ✅ | `app/services/refusal.py` |

Chat 主路徑：`retrieve_context` → MultiStepOrchestrator。  
閘門：`eval_foundation_queryplan_gate.py`。

剩餘（~15%）：更難多跳的自動 refinement、calculator 臂、拒答欄位級自動抽取。

---

## 5. Phase 3：跨語與編譯 — ✅ 核心完成

- 入庫後 `clause_projection` → Enclave Wiki `comparison`（ADR-007 不雙寫 Neo4j）
- translate／ETI 題讀投影；R19 接地
- 剩餘：更多語系自動觸發、投影品質抽驗流程產品化

---

## 6. Phase 4：持續驗收 — ✅ 骨架完成

| 集 | 規模 | 腳本 |
|----|------|------|
| 主黃金集 | 40 題（R01–R40） | `eval_answer_correctness.py` |
| 註解展開 | 67 題 | `build_golden_from_annotations.py` → `--with-expanded` |
| 對抗集 | 8 題 | `eval_adversarial_gate.py` |

規則：不準降難度；對抗集 PASS 才算 Phase 4 出口。

剩餘：客戶真實問題回流、對抗集擴到 30+、CI 每次 PR 強制重跑。

---

## 7. Phase 5：能力上限 — ✅ 就位盤點

`scripts/eval_capability_ceiling.py` → `artifacts/capability_ceiling_last_run.json`

已就位：`RETRIEVAL_RERANK=true`、強 LLM、雲端 OCR、條款投影、多步編排。  
深化：依失敗題驅動選 Voyage Rerank／多模態直讀等（成本不設限，但要消融證明）。

---

## 8. 三開源專案定位（不變）

| 專案 | 該做 | 不該做 |
|------|------|--------|
| RAGFlow | 解析／OCR | 唯一檢索大腦 |
| PipesHub | 連接器／ACL | 完整問答 |
| WeKnora | 編譯知識 | 搶 chunk 位 |

---

## 9. 下一步（逼近 90–100%）

1. ~~E010 party-role 語義~~（已證實為入庫問題，2026-08-03 解決，無需 party-role artifact）
2. ~~cache key 含 `filter_dict`~~（2026-08-03 已修＋契約測試）
3. 對抗集擴到 30+；主集＋展開集＋盲測集定期全量重跑納入 CI
4. MultiStep 對 compare／多跳加第二輪 refine
5. 盲測常態化：每批新文件類型入庫即出 20+ 題盲測，防回歸
6. e2e 測試隔離：對 dev DB 跑 e2e 會殘留測試租戶文件污染 FD-DELIVER，應自清或改用隔離 DB

---

## 10. 一句話

> **地基與大腦已接上；驗收與對抗集在跑；剩下是覆蓋深度與 OCR／多跳邊界，不是再從零長架構。**
