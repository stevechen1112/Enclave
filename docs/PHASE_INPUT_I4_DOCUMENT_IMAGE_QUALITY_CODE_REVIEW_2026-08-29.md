# Input I4 文件、表格、圖片品質工程 — Code Review

日期：2026-08-29
結論：**INTERNAL PASS；准入 Input I5。**

## Review 基線

- Commit：工作樹尚未提交；本文件以 2026-08-29 最終 diff、sealed corpus hash 與下列測試輸出為準。
- Schema revision：`input_i4_evidence_precision_001`。
- Input registry SHA-256：`12bc4c09444c59437daa72469ee1b1f38cad4711784315db3b7d0b456d033512`。
- I4 route contract SHA-256：`6b03f0421e21edee0800fc5bdc19fe488ade83dcfdc1e3c5b87e711fa96cea6c`，涵蓋 `/api/v1/knowledge/input-capabilities`、`/api/v1/knowledge/assets`、`/api/v1/knowledge/review-items`。
- Corpus manifest：`artifacts/input/i4_quality_corpus_manifest.json`，狀態 `SEALED_INTERNAL_SYNTHETIC`；不含客戶資料，也不宣稱現場認證。
- 品質基準與 replay：`artifacts/input/i4_quality_baseline.json`、`artifacts/input/i4_quality_report.json`。

## 已完成範圍

- 建立 server-owned 格式品質門檻：內容欄位正確率、locator coverage、parse success、provider regression、低信心覆核與固定 hash sampling。解析成功不再等於品質通過。
- DOCX 保留段落 index、標題 hierarchy 與表格列；PPTX 保留投影片號；XLSX 保留 worksheet、row、cell range、公式位置、合併範圍，並明示隱藏 sheet 不自動發布。
- 圖片 OCR 支援 EXIF orientation、低光 contrast、低信心四象限旋轉回復、多頁 TIFF，以及 OCR line normalized bbox；無精確區域時明示 whole-image fallback 並強制人工覆核。
- EvidenceSpan 新增 `paragraph_index`、`slide_number` 與 `locator_fallback`，review workspace 與 UI 能辨識精確位置及整張影像 fallback。
- 建立製造業形狀 sealed corpus：保養程序、進料檢驗、品質手冊、CNC 換線 SOP、BOM、首件檢驗、銘牌、旋轉標籤、低光標籤、多頁掃描表單。
- 每個 UI 開放文件格式均有格式品質 PASS 與 deliberate negative-control FAIL 樣本。PPTX、TIFF 在本環境完成內部證據後開放；DOC、XLS、HEIC 仍保持 UI 關閉。
- 舊文件頁移除硬編碼 accept 清單，改讀共用 Input capability contract；新增知識頁顯示格式內容品質門檻。

## Code Review 發現並修正

1. PPTX 對非 placeholder shape 直接讀 `placeholder_format` 會拋錯，但舊品質計分仍可能回傳 `poor` 而非 failed。現改用 `is_placeholder`，且任何 parser error 都 fail closed。
2. 第一版把文件品質門檻附到音訊／影片格式，語意錯誤。現只有文件／表格／圖片格式帶 I4 gate，長媒體留給 I5。
3. Whole-image fallback 原可能在 artifact 建立後才被補上，造成 quality state 過早 ready。現投影前即從所有 parse chunks 推導 fallback，強制 `review_required`。
4. 初版 TXT／CSV corpus 沿用一般 HR fixture，不足以支持製造業品質宣稱。現改為保養程序與進料檢驗資料並重新封存。
5. Excel 初版只有公式／合併數量，缺精確位置。現保存 formula cell 與 merged range，隱藏 sheet 保留名稱但不自動發布。
6. 舊 Documents UI 硬編碼格式，會與後端能力漂移。現與 `/knowledge/input-capabilities` 共用格式來源。

## 驗證結果

- Sealed corpus baseline + replay：`.csv/.docx/.jpeg/.jpg/.pdf/.png/.pptx/.tiff/.txt/.xlsx` 全部 PASS；provider drift 全部 PASS；各格式 deliberate failure sample 全部正確 FAIL。
- Backend quality/evidence/OCR regression：58 passed。
- Frontend full Vitest：34 files、119 passed。
- TypeScript、ESLint、Vite production build：PASS。
- Ruff：I4 新增檔案完整規則 PASS；修改既有 legacy 檔案的 fatal `F/E9` 檢查 PASS。
- Alembic fresh DB：upgrade 至 `input_i4_evidence_precision_001` → downgrade 至 I3 → re-upgrade，PASS；隔離測試 DB 已移除。
- `git diff --check`：PASS（僅 Windows line-ending 提示）。

## Review gate 對照

- Architecture：品質政策位於 core Input，無 domain pack 依賴；migration 可回滾。PASS。
- Tenancy/security：未新增跨租戶讀寫；hidden sheet 與 whole-image fallback 不自動發布。PASS。
- Reliability：fatal parser error fail closed；provider fallback 有 trace；sealed corpus 可 hash 驗證與重播。PASS。
- UX/accessibility：格式來自 server contract；degraded/品質門檻與 fallback 有可理解標示。PASS。
- Quality/evidence：所有 UI 開放格式具門檻、成功證據、失敗樣本與 locator round-trip。PASS。
- Performance/cost：旋轉復原最多四象限、sampling 由 hash 決定；大規模 live capacity 留待 I7。PASS WITH LATER LIVE GATE。
- Compatibility：Legacy upload route 保留；新增欄位具 server/Python default；DOC/XLS/HEIC 未被誤開。PASS。
- Documentation/claims：只宣稱內部 synthetic manufacturing-shaped corpus，不宣稱客戶／工廠現場認證。PASS。

## 未解風險與 waiver

- 真實手寫、油污／破損紙張、客戶舊 DOC／XLS、不同手機 HEIC 仍缺合法樣本；相關格式／能力不標 internally verified。
- 外部 OCR provider 的 production credentials drift 尚未執行；本輪只證明 native provider replay 機制與內部基準。
- I3 實體 iOS／Android capture 認證仍 pending。依使用者 2026-08-29 明確要求續行，僅豁免後續工程開發前置，不豁免商用／現場認證。
- 未執行 production migration，未部署。

在上述宣稱邊界下，I4 review gate 通過，可開始 Input I5。
