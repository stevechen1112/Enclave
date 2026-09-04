# Input I10：可泛化解析品質驗收與提升計畫

狀態：`BASELINE AUDITED / HOLD`

建立日期：2026-09-04

適用範圍：共用 Input、解析、證據、人工確認、發布與 Ask 核心；不綁定特定租戶或場景應用 Pack

本次真實種子資料：八策股份有限公司第二輪測試的 1 個音檔、1 張圖片及 3 支影片

## 1. 目的與產品原則

本階段的目的不是只把今天五個檔案修到能過，而是把它們轉成一套可重複、可量測、可擴充的品質契約，使 Enclave 面對新的租戶、格式、裝置、語言、內容領域與 Provider 時，仍能用相同方法判斷品質。

因此，五筆真實檔案只作為揭露問題的「種子案例」，不能成為硬編碼的產品規則。永久修復必須同時通過：

1. 原始失敗案例。
2. 同類但不同檔名、長度、編碼及裝置的鄰近案例。
3. 正常、低品質、無內容及損壞等反例。
4. 不同租戶與權限邊界。
5. 發布後 Ask 與引用的完整閉環。

核心判定分成五件不同的事，任何一項都不得冒充另一項：

```text
收到原檔
  → 處理器完成
  → 解析內容達標
  → 人工確認與正式發布
  → Ask 實際命中且引用正確
```

「成功上傳」不等於「解析正確」；「產生候選」不等於「已發布」；「資料庫有資料」也不等於「AI 問得到」。

## 2. 本次新增的可重複稽核能力

新增唯讀稽核程式：`scripts/audit_asset_parse_quality.py`

正式環境證據快照：`artifacts/input/INPUT_I10_FIRST_TENANT_PARSE_QUALITY_AUDIT_2026-09-04.json`

證據快照 SHA-256：`260e83bbc181cd958407eb95fdf525516591361768cd9000c0b9f7f83ccf02b5`

程式以租戶 UUID 為唯一範圍，套用正式 RLS context，只讀取目前未刪除來源，不修改原檔、候選、審核決策或發布狀態。它會對全部來源與衍生內容一次檢查：

- immutable revision、content hash、URI、大小及媒體長度是否存在；
- ingestion job 是否到達明確終態、是否殘留 active error；
- 每個 requested capability 是否產生對應 artifact family；
- Provider failure、重試次數與處理終態；
- artifact 種類、數量、空內容及重複 content hash；
- 人工候選是否都有 typed evidence span；
- 音訊／影片逐字稿的時間軸起訖、覆蓋尾端及 speaker 標記；
- `null` 未知信心與真正 `0` 分是否被正確區分；
- OCR 與程序候選的信心分布；
- 系統結構 artifact 是否錯誤暴露成人工工作；
- 審核決策、active KnowledgeUnit 與 release membership；
- 跨來源逐字稿的正規化字元相似度，作為同內容不同載體的一致性訊號。

稽核程式以 requested capabilities 決定預期產物，不用檔名或租戶名稱推測。例如請求 `transcribe` 才期待逐字稿，請求 `ocr` 才期待 OCR；未來仍應補上 `not_applicable`、`no_speech`、`no_text_detected` 等明確能力結果，避免把合理的「無語音／無文字」誤判成處理失敗。

## 3. 2026-09-04 正式環境真實基線

執行時間：2026-09-04 12:48（Asia/Taipei）

部署版本：`force-rls-7f9416f`

稽核範圍：

| 指標 | 結果 |
|---|---:|
| 未刪除來源 | 5 |
| 全部衍生 artifact | 153 |
| typed evidence span | 145 |
| 顯示給人工確認的候選 | 122 |
| 人工決策 | 0 |
| active published KnowledgeUnit | 0 |

### 3.1 自動 Gate 結果

| Gate | 結果 | 觀察值 | 判定 |
|---|---|---:|---|
| 收件完整性 | PASS | 5/5 | 五筆均有 immutable revision、hash、URI 與原檔大小 |
| 處理器完整性 | PASS | 5/5 | 均完成一次處理、無 active error、無 Provider failure，所請求產物種類存在 |
| 人工候選證據完整性 | FAIL | 121/122，99.18% | 可人工處置的每一筆都必須有證據，標準為 100% |
| 信心值語意 | FAIL | 26 筆影片逐字稿使用 0 sentinel | 未提供信心應為 `null`，不能顯示成 0% |
| OCR 品質底線 | FAIL | 最低來源平均 52% | 圖片 OCR 不可直接發布，需替代路徑或人工校正 |
| 人工工作量設計 | FAIL | 32 筆結構資料進入人工佇列 | speaker turn、scene、timeline 不應成為發布決策 |
| 語意正確率 | NOT EVALUATED | 尚無 ground truth | 後端完整性與信心分數不能取代真實文字對照 |
| 發布與 Ask | NOT RUN | 0 決策、0 active unit | 本批尚未完成發布、檢索及引用閉環 |

總結：`HOLD`。本批證明收件與處理器可以運作，但尚不能證明解析品質與正式問答已達產品驗收。

### 3.2 各來源結果

| 來源 | 技術處理 | 主要產物 | 品質判定 |
|---|---|---|---|
| 人資音檔，92.5 秒 | PASS | 20 段逐字稿，尾端覆蓋 98.72%，20/20 有時間碼 | 技術完整；未提供 confidence；仍有少數辨識錯字，語意驗收待 ground truth |
| IMG_8592.jpeg | PASS | 1 筆整合文字、19 個 OCR region | OCR 全部為 52%，文字明顯破碎；整合文字缺 typed evidence，FAIL |
| 員工自願不保勞保影片，80.2 秒 | PASS | 4 段逐字稿、6 幀、5 OCR、程序候選 | 時間軸達 96.41%；OCR 平均 74.68%；程序信心 41.49%；需確認 |
| 員工責任制影片，129.8 秒 | PASS | 16 段逐字稿、9 幀、8 OCR、程序候選 | 時間軸達 97.48%；OCR 平均 85.25%；程序信心 28.42%；簡繁混用明顯 |
| 職場性騷擾影片，80.3 秒 | PASS | 6 段逐字稿、6 幀、6 OCR、程序候選 | 時間軸達 93.91%；OCR 平均 73.88%；程序信心 36.94%；簡繁混用明顯 |

音檔與「員工自願不保勞保」影片為相近內容，兩份逐字稿正規化字元相似度為 97.41%。這是跨載體一致性的正面訊號，但不是字詞完全正確的證明；例如兩者仍分別出現「人字長／人資長」、「裁發／裁罰」、「應付單／應負擔」等差異。

## 4. 目前揭露的泛化缺陷

| ID | 嚴重度 | 泛化問題 | 影響範圍 | 狀態 |
|---|---:|---|---|---|
| I10-001 | P1 | 未知 ASR confidence 被存成 0 | 所有不回傳 confidence 的影音 Provider | I10-2 IMPLEMENTED / LOCAL REVIEW PASS |
| I10-002 | P1 | 圖片低品質 OCR 只有單一路徑，沒有可靠 fallback／重處理策略 | 掃描、手機斜拍、表格、低對比、多欄圖片 | OPEN |
| I10-003 | P1 | 一筆 human-actionable extracted text 缺 typed evidence | 所有由區塊聚合成整合文字的投影 | OPEN |
| I10-004 | P1 | 32 筆結構 artifact 被當成人工發布工作 | 所有影片的 speaker、scene、timeline | OPEN |
| I10-005 | P1 | 來源分組只有瀏覽效果，沒有來源層級確認／發布 | 多段逐字稿、OCR、表格及影片 | OPEN |
| I10-006 | P1 | 0 個發布單元，尚未證明影音 KnowledgeUnit 能被正式 Ask 讀取 | 非傳統 Document 類型 | OPEN |
| I10-007 | P2 | 逐字稿簡繁混用，沒有 tenant locale 正規化策略 | 台灣繁體中文租戶 | OPEN |
| I10-008 | P1 | confidence 未經 Provider calibration，不能跨 OCR／ASR 模型直接比較 | 所有可替換 Provider | I10-2 CONTRACT IMPLEMENTED；校準資料仍待 I10-3／I10-6 |
| I10-009 | P1 | 缺少人工 ground truth，無法計算 CER／WER、表格準確率與時間碼誤差 | 全部格式 | OPEN |
| I10-010 | P1 | capability 只有「要求了什麼」，缺少 available／degraded／not_applicable／failed 的逐能力結果 | 無語音影片、無文字圖片、供應商降級路徑 | I10-2 IMPLEMENTED / LOCAL REVIEW PASS |

這些缺陷均不得以特定檔名、影片主題、八策租戶 ID 或固定段數修補。

## 5. 可泛化品質模型

### 5.1 共通 Gate

每種 Input 都必須先通過：

1. **G0 收件完整性**：原檔 hash、大小、媒體型別、建立者、租戶、ACL、版本與 retention snapshot 完整。
2. **G1 處理可靠性**：工作有明確狀態、錯誤分類、有限重試、Provider 與版本，沒有無限 running 或靜默降級。
3. **G2 內容完整性**：依 requested capability 回傳 artifact 或明確 `not_applicable/no_content/degraded/failed`，不允許缺產物卻宣稱成功。
4. **G3 證據完整性**：所有可發布文字、表格、事件及程序必須 100% 回到頁碼、區塊、儲存格、時間碼或畫面。
5. **G4 品質可解釋性**：未知分數為 `null`；分數需標記 Provider／版本及校準版本；低於門檻自動送人工或 fallback。
6. **G5 人工負荷**：只讓人決定會影響正式知識的內容；內部結構與重複區塊不得成為待辦。
7. **G6 發布真實性**：核准必須建立 active release，且 answer-ready 與實際 Ask serving path 一致。
8. **G7 引用真實性**：Ask 命中後可打開正確原始證據；未發布、撤權或刪除內容不得被引用。

### 5.2 各模態品質 Gate

#### 文件與 PDF

- 原生文字與 OCR 路徑分開評估。
- 頁數、標題層級、段落順序、表格、頁首頁尾與附件不得靜默遺失。
- 掃描 PDF 需評估旋轉、傾斜、陰影、直排、多欄與印章遮擋。
- 文字以 CER／關鍵欄位 exact match 評估；版面以 reading-order 與 locator coverage 評估。

#### 圖片

- 分成乾淨截圖、手機拍照、表單、表格、白板、設備銘牌、標籤及現場遠景。
- 自動做旋轉、deskew、裁切、對比及解析度檢查；必要時採不同 OCR Provider ensemble。
- Provider confidence 只用於分流；正式品質以人工 ground truth 的 CER、關鍵欄位召回率及 bbox coverage 驗收。
- 無文字圖片必須回報 `not_applicable/no_text_detected`，不能當處理失敗。

#### 音檔

- 涵蓋 WAV PCM16／24、M4A、AAC、MP3、手機錄音、會議室、機台噪音、多人重疊、台語夾雜及長時間靜音。
- 評估 CER／WER、專有名詞、數字單位、speaker diarization、時間碼 P95 誤差、漏段與重複段。
- 未提供 confidence 必須為 `null`；不可偽造成 0%。
- 長音檔需分段但保持跨段語境、順序與無重複合併。

#### 影片

- 分別驗收音軌、逐字稿、關鍵幀、OCR、場景、事件、跨模態時間軸與程序候選。
- 無音軌、無字幕、純簡報、手持晃動、直式影片、低幀率與長時間固定畫面都需列入反例。
- 程序候選不能只以模型 confidence 驗收；需對步驟順序、前置條件、禁止動作、風險與證據時間碼做結構化 precision／recall。
- 場景、speaker turn 與 timeline 是支援證據，不直接要求一般使用者逐筆核准。

#### 試算表與結構化資料

- 評估工作表、表格範圍、合併儲存格、公式與顯示值、日期／幣別／百分比、空白列、隱藏欄及跨表關聯。
- 關鍵欄位需 exact match；列級引用必須回到 sheet、cell range 與原始版本。
- 欄位推斷與原始值分開保存，AI 不得覆寫正式來源。

## 6. 可泛化測試資料集

品質資料集分四層，不以單一客戶資料替代通用測試：

### S0 真實問題種子

- 保留本次五筆的匿名化特徵與失敗模式。
- 目的為重現真實摩擦，不作唯一驗收依據。
- 原始客戶內容不直接進公開或跨租戶測試集。

### S1 鄰近案例

每個問題至少加入：

- 同格式、不同裝置／編碼；
- 同內容、不同載體；
- 同 Provider、不同語言與長度；
- 品質略高及略低於門檻的 boundary cases；
- 空白、無語音、無文字、損壞及副檔名偽裝反例。

### S2 版本化標準語料

- 使用已取得授權或自行建立的文件、圖片、音訊、影片及試算表。
- 保存 ground truth、證據定位、資料分類、生成方式與 SHA-256。
- 每次 Parser、OCR、ASR、模型、prompt 或切段策略改版都重跑。

### S3 租戶驗收集

- 每個新租戶選取代表其設備、用語、文件與環境的少量真實樣本。
- 只校準詞彙、門檻與 fallback，不建立租戶專屬硬編碼。
- 結果只對該租戶可見；跨租戶只保留匿名化統計。

## 7. 建議量化門檻

以下為 I10 起始門檻，完成 S2 校準後可依模態與風險分級調整，但調整必須版本化：

| 指標 | 起始門檻 |
|---|---:|
| 收件與不可變來源完整率 | 100% |
| requested capability 有結果或明確不適用 | 100% |
| 可人工處置／可發布候選 evidence coverage | 100% |
| 空白卻標記成功的文字 artifact | 0 |
| 未知 confidence 被表示為 0 | 0 |
| 結構 artifact 進入一般人工佇列 | 0 |
| 乾淨繁中印刷 OCR CER | ≤ 5% |
| 中等品質手機照片 OCR CER | ≤ 10%，否則人工確認 |
| 清楚單人語音 ASR CER | ≤ 8% |
| 一般會議／現場語音 ASR CER | ≤ 15%，超過即人工確認或 fallback |
| 關鍵數字、單位、料號與法條 exact match | 100% 或明確標示待確認 |
| 音訊／影片時間碼 P95 誤差 | ≤ 2 秒 |
| 來源層級人工處理 | 一個來源可完成一次低風險確認；例外獨立處理 |
| 發布後代表性 Ask 命中率 | 100% |
| Ask 引用可開啟且定位正確 | 100% |
| 未發布／刪除／撤權來源命中率 | 0% |

法律、職安、機台控制及正式 SOP 等高風險內容，即使文字準確率達標仍不得自動升格成正式規則。

## 8. I10 實作 Phase

每個 Phase 都遵守：實作 → 自動測試 → Code Review → 回歸 Gate → 才進下一 Phase。

### I10-0：品質稽核基線

- 建立 tenant-scoped 唯讀解析品質稽核程式。
- 對正式五筆來源與 153 個 artifacts 執行基線。
- 固定 JSON 證據與本驗收文件。
- 狀態：`IMPLEMENTED / CODE REVIEW PASS`。

### I10-1：Ground truth 與評分器

- 定義各格式 truth schema：文字、表格、時間碼、speaker、bbox、程序步驟。
- 建立 CER／WER、欄位 exact match、時間碼 drift、evidence coverage 與程序 precision／recall。
- 建立 S1 鄰近案例及 S2 版本化標準語料。
- 稽核報告必須顯示樣本數與信賴區間，禁止只報平均值。
- 狀態：`QUALITY CONTRACT IMPLEMENTED / CODE REVIEW PASS`。共用評分器已完成；S1／S2 真實 ground truth corpus 的蒐集與標註仍為本 Phase 的資料工作，產品品質維持 HOLD。

### I10-2：信心與能力結果契約

- 將未知 ASR confidence 由 0 修為 `null`，並修復既有錯誤投影。
- confidence 加入 Provider、模型、版本與 calibration version。
- 每個 requested capability 回傳 `available/degraded/not_applicable/failed` 與原因。
- UI 不再把「未知」顯示為「0%低信心」。
- 狀態：`IMPLEMENTED / CODE REVIEW PASS (LOCAL) / NOT DEPLOYED`。詳見 `PHASE_INPUT_I10_2_CONFIDENCE_CAPABILITY_CONTRACT_CODE_REVIEW_2026-09-04.md`。

### I10-3：多路解析與品質 fallback

- 圖片／掃描先做影像品質分析與前處理。
- 低品質 OCR 自動嘗試可驗證的替代 Provider／策略，保留各版本但只選一個候選供人工確認。
- 音訊／影片加入 terminology hint、語言／locale 正規化及長段落合併品質檢查。
- Parser／Provider 切換由能力與品質決定，不依租戶或檔名硬編碼。

### I10-4：來源層級人工確認與發布

- 原始低風險文字以來源為單位確認，一次發布成可問答證據。
- 只把低信心區段、關鍵欄位、衝突及高風險 AI 推論列為例外。
- speaker、scene、timeline 等結構資料移出一般人工佇列。
- 來源建立者可確認低風險原文；高風險程序仍需另一位 Owner。
- 「知識頁」與「資料庫／已發布知識」的名稱和狀態分開。

### I10-5：發布、Ask 與引用真實 Gate

- 確認 KnowledgeUnit read mode 與 answer-ready 使用同一條 serving truth。
- 每種來源發布後執行只能由該來源回答的問題。
- 驗證回答內容、來源、版本、時間碼／頁碼／bbox deep link。
- 驗證未發布、撤權及刪除後不可再命中。

### I10-6：泛化回歸與首租戶複測

- 原始五筆、S1 鄰近案例及 S2 標準語料全部重跑。
- 不同格式、長度、裝置、語言、Provider 與 tenant isolation 皆有證據。
- 李永仁只需完成符合真實工作的來源確認、Ask 與引用操作，不再替系統逐筆清理技術 artifact。
- 全部 Gate 通過後，才將本輪由 `HOLD` 改為 `ACCEPTED`。

## 9. 本階段完成定義

I10 不能以「這五筆現在能問」作為完成。必須同時滿足：

1. 稽核器能對任意租戶與新來源重跑，沒有檔名／租戶硬編碼。
2. 每個格式都有 ground truth 指標、鄰近案例與反例。
3. 本次四個自動 blocking gates 全數關閉。
4. 語意準確率由 `NOT EVALUATED` 變成有樣本數的 PASS。
5. 五筆來源完成合理的人工作業、發布、Ask 與引用。
6. 新 Provider 或 Parser 版本若退步，CI／release gate 能阻擋。
7. 每個 Phase 均有獨立 Code Review 紀錄與可重跑證據。

## 10. 現階段允許與禁止的產品宣稱

目前可以宣稱：

> 本次五筆真實音訊、圖片與影片均成功收件並完成處理器流程；系統可產生逐字稿、OCR、時間碼、關鍵幀及程序候選。

目前不可宣稱：

> 所有解析結果品質合格、已可直接發布，或所有音訊／圖片／影片都能可靠被 AI 問答。

目前正確狀態：

> 真實基線已建立，收件與處理完整性通過；解析品質、人工負荷與發布問答仍為 HOLD，進入 I10 泛化品質提升。
