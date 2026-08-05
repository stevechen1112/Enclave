# ADR-010：掃描／OCR 入庫交付不變量

**狀態**：已接受（部分已落地；缺口見後果）  
**日期**：2026-08-03  
**決策者**：Enclave 技術團隊  
**關聯**：ADR-002、label integrity、`docs/FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN.md` Phase F1  
**實作錨點**：`app/services/parse_pipeline.py`（`SCAN_PARSE_STRICT`、雲端 OCR 觸發）、`tests/test_scan_parse_delivery.py`

---

## 背景

歷史問題：

1. 掃描 PDF 走 DeepDOC 路由卻落到 `native/text_fallback`，仍標 `completed` → 問答複述髒／空語料。  
2. `parse_engine=ragflow/deepdoc`、`ocr_used=true` 曾出現標籤與上游不一致（假綠）。  
3. 2026-08-03：`000_nueip 合約(1).pdf` 因環境缺 poppler 解析失敗；若錯誤被吞或標成功，會造成「預期合約檔不在庫」的盤點／主題題系統性失敗。

沒有交付不變量，上層 Catalog／Fusion／編排都建立在沙上。

## 決策

**掃描／OCR 路徑的「成功」只允許一種含義：產出可檢索、標籤誠實的文字；否則必須 failed，禁止靜默 completed。**

### 不變量

1. **禁止假完成**  
   - 當路由為掃描／DeepDOC／VLM 時，`parser == native/text_fallback` 不得導致 `status=completed`（預設 `SCAN_PARSE_STRICT=true`）。  
   - 允許顯式 `SCAN_PARSE_STRICT=false` 僅供實驗室；不得作為產品預設，不得在對外宣稱中使用。

2. **空產能／髒產能必須處理**  
   - 觸發條件含：text_fallback、scan 未 OCR、字數過低、髒 OCR 啟發式（含間隔 CJK、低有用字元密度等）。  
   - 處理：雲端 OCR 救援成功並改標真實引擎，或整單 `failed`。  
   - 禁止「字很多但不可讀」仍當成功。

3. **標籤誠信**  
   - `parse_engine`／`ocr_used`／`layout_recognize_actual` 必須反映真實路徑（延續 label integrity 閘門）。  
   - 雲端救援必須在 metadata 記錄 `cloud_ocr.trigger` 與 `original_engine`。

4. **環境依賴失敗要可行動**  
   - 缺 poppler／無法取頁數等 → `failed` + 穩定、可搜尋的 `error_message`（含缺依賴關鍵字）。  
   - 不得標 completed，不得清空錯誤後重試成假成功。

## 理由

1. 問答品質的下限是語料；假完成會讓所有檢索指標失真。  
2. 與「能力宣稱邊界」一致：不能宣稱 DeepDOC／OCR 已交付卻存 fallback。  
3. 為 ADR-008 Catalog 提供可信 `status=completed` 前提。

## 約束

- 不得以降低嚴格度換取閘門全綠。  
- 不得在未救援成功時把 fallback 文字標成 `ragflow/deepdoc`。  
- 存量已 completed 的 fallback 必須進入清冊重跑，不得假裝不存在。

## 後果

### 已落地（2026-08-03）

- `ScanParseDeliveryError` + `SCAN_PARSE_STRICT`  
- 雲端 OCR 觸發擴充與髒文本啟發式  
- `tests/test_scan_parse_delivery.py`  
- compose／`.env` 傳入相關旗標（環境各異）

### 仍待收斂（Phase F1）

- 執行映像保証 poppler／頁渲染依賴，或標準化錯誤  
- 存量 fallback／failed 清冊與重入庫  
- `artifacts/foundation_delivery_last_run.json` 閘門產物  
- 與 CI／preflight 掛接

## 落地對應

- 計畫 Phase F1：`FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN.md`  
- 閘門：FD-DELIVER  
- 既有：`scripts/eval_label_integrity.py`、`tests/test_label_integrity_gate.py`  
