# Input I10：泛化能力重新檢視與修正紀錄

狀態：`RE-REVIEW COMPLETE / PRODUCT QUALITY HOLD`

日期：2026-09-04

## 1. 為什麼昨天修完、今天真實測試仍立刻出現問題

這次不是把責任歸因於一支影片、一張圖片或單一 Provider。重新檢視後，根因是過去的驗收證據被錯誤放大：系統把「某一層成功」當成「整個產品可用」。

過去同時存在以下不同事實：

- 檔案格式可以開啟；
- ingestion job 可以到達終態；
- synthetic corpus 可以產生預期 artifact；
- evidence locator 的資料結構存在；
- 真實使用者可以上傳檔案；

但這些都不能各自證明：

- 真實台灣製造業內容被正確辨識；
- 使用者看得懂並能完成確認與發布；
- 已發布內容真的走進 Ask 的 serving path；
- 回答能開回正確頁碼、區域或時間碼；
- 換一台手機、另一種口音、另一個 Provider 或下一版映像仍然成立。

因此，本次問題的主要原因不是「昨天沒寫測試」，而是測試的證明範圍沒有被產品宣稱嚴格限制。

## 2. 重新核對 I0～I9 後的證據真相

| 舊證據 | 真正證明的事 | 不能證明的事 |
|---|---|---|
| `i0_golden_corpus_manifest.json` | Input contract 與回歸種子存在 | 文件、圖片、音訊、影片的現場品質認證；其所有 modality 原本就標示 `quality_certified: false` |
| I4 `SEALED_INTERNAL_SYNTHETIC` PASS | 內部合成文件／圖片在當時環境可通過格式與 locator Gate | 客戶舊檔、油污／手寫／手機實拍、真實 OCR 準確率與跨版本可重現性 |
| I5 codec/timeline PASS | 合成音訊／影片可由 ffprobe 開啟，媒體邊界資料可計算 | 工廠語音 CER/WER、口音、噪音、多人、真實手機來源及 24 小時佇列穩定性 |
| multimodal contract corpus PASS | 終態、evidence locator、review routing 的契約可運作 | 原始音訊／影片的語意正確率與使用者旅程 |
| I9 正式 smoke | 文字來源可完成一條 Ask 路徑，媒體可走到 `review_required` | 每一種媒體都已完成確認、發布、Ask、引用與撤權閉環 |
| 2026-09-04 八策 5 筆真實來源 | 5/5 收件及 processor completion；能產生 153 筆 artifacts | 語意品質、可用的人工作業、發布與 Ask；目前仍為 HOLD |

舊文件其實已經留下多個 declared gaps，但最後的產品 Ready 判斷沒有自動繼承這些缺口。這是治理與 Gate 聚合缺陷，不只是文字說明不夠清楚。

## 3. 本次重新檢視新增發現

### 3.1 Gate 分散，沒有單一「宣稱上限」

目前文件、媒體及多模態各有不同 evaluator。各 evaluator 可以各自 PASS，但沒有共同規則回答：「這份證據最多允許我們宣稱到哪一層？」

本次已新增四層 claim model：

1. `contract`：資料結構、狀態機或 API 契約成立。
2. `mechanical`：檔案可開啟、處理器可執行、artifact 可產生。
3. `semantic`：以獨立人工 ground truth 證明內容、關鍵欄位及定位正確。
4. `journey`：真實來源完成發布、Ask、引用、撤權與權限隔離。

synthetic 或 contract-only 證據不能越級證明 semantic；解析報告也不能單獨證明 journey。

### 3.2 舊 PASS 沒有綁定可重現 runtime

本次在目前 Windows 工作環境重新執行 I4 corpus，文件格式可通過，但 PNG、JPG、JPEG、TIFF 因本機不存在 Tesseract runtime 全數失敗。正式 Dockerfile 有安裝 Tesseract 與繁中語言包，因此這不直接代表正式環境 OCR 已故障；它證明的是舊報告沒有把 OS、native dependency、模型／Provider 版本及 image digest 當成 PASS 的必要身份。

往後每份品質報告必須綁定：

- source commit、release image digest、schema head；
- OS／CPU architecture；
- ffmpeg、ffprobe、Tesseract、Poppler、LibreOffice 版本；
- OCR／ASR／LLM Provider、模型、prompt、calibration version；
- corpus hash 與每個原始樣本 hash。

### 3.3 平均值會掩蓋單一高風險錯誤

如果九筆完全正確、一筆把 `6.5 BAR` 辨識成 `65 BAR`，平均 CER 可能仍好看，但現場結果不可接受。本次評分器已改成 required slice 逐一判定，任何一筆已量測的關鍵欄位、定位或語意失敗都會使該 slice FAIL，不能被全體平均值沖淡。

檢視實作時也實際抓到一個評分器錯誤：原本寬鬆正規化會移除小數點，使 `6.5 BAR` 與 `65 BAR` 被視為相同。本次已改為關鍵欄位保留小數點、正負號及分隔符，只忽略 Unicode 形式與空白差異。

### 3.4 Provider confidence 不是 ground truth

52% OCR confidence、0% ASR confidence 或 97% 跨來源相似度都只能作為 triage signal：

- 未回傳 confidence 必須是 `null`，不是 0；
- 不同 Provider 的 confidence 未校準前不能直接比較；
- 兩份逐字稿彼此相似，可能只是共同犯同一個錯；
- 正式準確率必須由 CER/WER、關鍵欄位 exact match 及人工 truth 計算。

因此，正式 5 筆來源稽核仍可用來發現異常，但不能單靠 heuristic confidence 發出語意 PASS。

### 3.5 稽核器本身也不能被誤當成大規模認證

`audit_asset_parse_quality.py` 目前能做租戶隔離的唯讀快照，適合本次 5 筆來源，但尚有以下邊界：

- 一次載入租戶目前來源與 artifacts，尚未完成批次／游標化；
- human candidate kind 與 capability mapping 仍是程式常數，可能與 registry 漂移；
- timeline reach 只表示資料到達影片尾端附近，不是時間碼準確率；
- simplified character、跨來源相似度及 provider confidence 皆為警示訊號，不是語意評分；
- 尚未包含 latency、成本、fallback adoption、佇列壓力及原檔重新雜湊。

因此它的定位已明確限制為「production triage audit」，不能單獨簽發產品品質認證。

## 4. 已完成的真正泛化修正

本次新增的是共用驗收機制，不含租戶名稱、檔名、影片主題或固定段數：

- 新增 evidence class 與 claim ceiling，阻止合成 PASS 被宣稱成真實語意 PASS；
- 新增完整文字 CER 與中英混合 token WER；
- required slice 必須逐一有資料，不可缺資料仍 PASS；
- 每個 slice 預設至少 5 個 truth-backed 樣本，樣本不足為 HOLD；
- 每個 slice 公布成功數、分母及 Wilson 95% 信賴區間；
- 單筆 measured failure 不可被平均值隱藏；
- 關鍵數字、單位、料號及正式欄位使用保留標點的 exact match；
- 支援時間碼 boundary P95，而不是只看是否有 start/end；
- `no_speech`、`no_text`、`not_applicable` 可在有 ground truth 時成為正確結果，不會被誤判成解析失敗；
- unknown confidence 與 measured zero 有明確不同語意；
- I4 與 I5 報告分開顯示 `execution_status` 與 `certification`：機械流程可 PASS，但 semantic certification 仍 HOLD。

## 5. 現在的正確產品判斷

### 已經能證明

- 八策第二輪 5 筆來源均已進入正式資料庫並完成處理器流程；
- 音訊、圖片、影片均能產生相應衍生內容；
- 新品質契約可以阻止 synthetic、樣本不足、缺 slice、單筆高風險錯誤及未驗證 ground truth 被誤判成產品 Ready。

### 仍不能證明

- 目前 5 筆來源的語意均正確；
- 李永仁能以合理工作量完成確認與發布；
- 媒體發布後一定被現行 Ask read mode 使用；
- 每一筆引用都能開回正確時間碼／畫面；
- 其他租戶、裝置、噪音、口音、長檔及 Provider 版本具有相同品質。

全產品狀態仍為 `HOLD`，不能因為今天「資料進資料庫」就再次宣稱完成。

## 6. 接下來必須依序關閉的 Gate

### 6.1 李永仁正式身分的唯讀核對

2026-09-04 以正式環境、正式 RLS context 與後端實際服務邏輯核對：

- `https://kachu.tw/health` 回傳 200；release 為 `force-rls-7f9416f`，資料庫 ready；
- 李永仁帳號存在，狀態 `active`、角色 `owner`、email 已驗證；
- 八策目前 5 個未刪除來源：影片 3、圖片 1、音訊 1；
- 5 個來源全部為 `awaiting_review`，對應 job 全部為 `review_required`；
- review workspace 回傳 5 個來源群組、122 個人工項目；
- 122 個項目全部被 `separation_of_duty` 阻擋，另有 1 個同時缺 evidence；
- active KnowledgeUnit 為 0；`KNOWLEDGE_UNIT_READ_MODE` 仍為 `shadow`。

因此「李永仁的端到端流程已經通了」目前答案是**沒有**。他建立來源後，現行程式不分風險一律禁止建立者自行確認，所以李永仁不能獨立完成這 5 筆；即使由另一位 Owner 核准，仍要驗證 shadow read mode 下 Ask 是否真的採用新 KnowledgeUnit。

這也確認 I10-4 與 I10-5 不是 UI 微調，而是產品 truth contract：低風險原文與高風險推論應採不同職責分離規則，且「answer-ready」必須和實際 serving path 一致。

瀏覽器自動化環境本次未提供任何可控制瀏覽器（Chrome 與內建 browser 均 unavailable），所以沒有把後端核對冒充成 UI 實測。正式伺服器保存的建帳臨時密碼已無法登入，代表李永仁已變更密碼；若要由本工作階段完成真正登入後瀏覽器驗收，需要李永仁目前密碼及一個可用的受控瀏覽器工作階段。

1. I10-2：修正 unknown confidence、逐能力結果與 runtime identity。
2. I10-3：影像前處理、多路 OCR／ASR fallback、繁中 locale 與術語策略。
3. I10-4：來源層級確認與發布，結構 artifact 移出一般人工待辦。
4. I10-5：統一 answer-ready 與 Ask serving truth，完成每種媒體的發布／引用／撤權測試。
5. I10-6：以匿名化真實種子、鄰近案例、反例、標準 truth corpus 及租戶驗收集進行回歸。

每個 Phase 必須先完成實作、自動測試與 Code Review，前一個 Phase 未通過不得把後一個 Phase 標成完成。

## 7. 防止再次重演的發布規則

從本次起，任何「可找首租戶」「Input 已完成」「媒體可問答」宣稱必須附同一份 evidence matrix，至少包含：

- 每個 modality 的 evidence class 與 claim ceiling；
- required slices、樣本數、分母、Wilson interval 及 open gaps；
- production release identity 與 runtime dependency fingerprint；
- 真實發布→Ask→引用→撤權結果；
- 實體 iOS／Android 或等價真機測試；
- 明確列出 NOT RUN、NOT EVALUATED、HOLD，不得省略。

只要任一必要列為 HOLD、NOT RUN 或 NOT EVALUATED，產品總結就不得寫成 READY。
