# 能力宣稱邊界（Capability Claims）

> 來源：`CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md` 閘門結果（2026-08-02）。  
> 決策產物：`artifacts/capability_fanout_decision.json`。  
> **接線完成 ≠ 價值證明完成。**

## 已證明（可對外宣稱）

| 宣稱 | 閘門 |
|------|------|
| 掃描 PDF 可由「完全不可檢索」轉為「可檢索」（DeepDOC vs PlainText） | CV-RF-01a 覆蓋率 PROVEN |
| 乾淨印刷掃描的欄位抽取可達可用水準（CER ≈ 0.18–0.33） | CV-RF-01b 子集 |
| RAGFlow 檢索在可答黃金題上 Hit@5 = 14/15（vs 本機 canonical 0/15） | E1 answerable-only PROVEN |
| BookStack → PipesHub ACL 搜尋：fixture 零洩漏 | CV-PH-03 |
| WeKnora Auto-Wiki 真實編譯（含 source_refs）；sole-source 撤權後不可見 | CV-WK-03、CV-WK-06；瀏覽 UI＋管理員手動編輯（新增 revision）已上線（`/knowledge/wiki`，2026-08-03） |
| page/bbox lineage 可從 DeepDOC `positions` 寫入 Citation | B4 / lineage 50/50 |
| Specialist 路徑延遲 p95 ≈ 432ms（預算 3000ms）；旗標預設關閉 | CV-RF-06 PASS（仍不進預設 fan-out） |

## 已接線、未證明（不得當賣點）

| 能力 | 現況 |
|------|------|
| DeepDOC 對**全語料**抽取品質 | CV-RF-01b 整體 MARGINAL／FAIL（手寫／拍照 CER 0.8+）；雲端四臂：luna 24.2%（幻覺風險）、terra 25.8%、**gemini-3-flash-preview 與 mistral-ocr-4 並列最佳 30.3%**（命中欄位完全相同、DeepDOC 嚴格超集、手寫切結書 4/4），仍未達 20pp 門檻（`cloud_vision_{ocr,terra,gemini,mistral}_ablation_last_run.json`）。2026-08-03 起雲端 OCR 已接為**選配增強臂**（`CLOUD_OCR_PROVIDER`，預設關閉；僅在主解析產出過少時觸發，見 `app/services/cloud_ocr.py`） |
| parent-child 分塊 | 結構已啟動；Hit@5 vs naive = NO_VALUE（天花板） |
| 切片模板 laws/manual/table | CV-RF-02：與 naive 同 Hit@5（NO_VALUE）；table 臂失敗 |
| RAPTOR | CV-RF-04 NO_VALUE（OpenAI gpt-5.6-luna 真實跑完索引 465.8s；Hit@5 90% vs 90% Δ=0）；預設關閉 |
| RAGFlow GraphRAG（RF-05） | CV-RF-05 NO_VALUE（gpt-5.6-luna 真實建圖 225.3s；Hit@5 Δ=0）；預設關閉 |
| WeKnora Neo4j GraphRAG | gpt-5.6-luna 重抽取後 **3,239 ENTITY／3,017 關係**（8B 時代僅 8 個類型標籤節點）——接線品質證實依賴模型規模；價值消融仍 NO_VALUE；見 ADR-007 |
| PipesHub 企業脈絡圖 | CV-PH-05 NO_VALUE（ACL 圖≠知識圖；useGraph 無增益） |
| PipesHub LOCAL_FS | C2 BLOCKED（此映像 registry 無 LOCAL_FS）；BookStack 已證真實 connector |
| RAGFlow 拒答不可答問題 | E1：過度召回 0/5 refuse |
| SharePoint／Drive connector | OPEN_GATES（需 OAuth／客戶租戶） |

## 未啟用（預設關閉）

- `RAGFLOW_SPECIALIST_ENABLED`（E2：拒答缺口未解前不進預設 fan-out）
- RAPTOR / Graph index（僅核准 KB 可選開）
- WeKnora GraphRAG 產品路徑（雖已有 extract 證據，Δ 未 PROVEN）
- 雙邊同時 parent-child（RAGFlow ⊕ WeKnora）— 計畫禁止

## 文件對照

- 產品行銷敘事：`PRODUCT_INTRODUCTION.md`（不因本表改寫行銷語氣；本表為工程／銷售誠信邊界）
- 操作手冊：`USER_MANUAL.md`
- Graph 雙庫邊界：`docs/adr/ADR-007-graph-store-boundary.md`
