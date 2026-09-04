# Input I10-2：信心與能力結果契約 Code Review

狀態：`PASS (LOCAL) / NOT DEPLOYED`

日期：2026-09-04

範圍：文件、圖片、音檔與影片 Input 的終態能力結果、信心語意、Provider 身分、執行環境身分、既有資料修復及資產詳情 UI。

## 1. 完成內容

### 1.1 信心值不再混淆

- `TranscriptionResult.confidence` 預設由 `0.0` 改成 `None`。
- OpenAI 目前沒有回傳可校準的 ASR confidence，因此新音訊與影片逐字稿保存 `null`，不再偽裝成 0%。
- 若未來 Provider 明確供應實測 `0.0`，`confidence_provider_supplied=true` 時仍會保留真正的零分。
- artifact 同時記錄 Provider、套件版本、模型、是否由 Provider 提供分數，以及 calibration version。
- OCR 的原生分數明確標示為 `provider_native_uncalibrated`，不能與 ASR 或其他模型直接互相比較。
- 文件解析分數區分為 Provider 原生分數、內部品質 heuristic 與未知；雲端 OCR 接手後不得沿用前一個解析器的舊分數。

### 1.2 每項處理能力都有真實結果

新增 `input-capability-results.v1`，每個 requested capability 必須有且只有一個結果：

- `available`：能力確實完成並有符合定義的結果。
- `degraded`：可以使用，但有明確限制或尚未量測品質。
- `not_applicable`：來源合理地沒有該內容，例如無音軌、無語音或無畫面文字。
- `failed`：能力應執行但沒有完成。

所有非 `available` 結果必須附 machine-readable `reason_code`。未回報的 requested capability 會 fail closed 成 `capability_result_missing`；處理工作若失敗，所有尚未回報的能力會得到該錯誤代碼，而不是只留下模糊的 job failure。

### 1.3 合理空結果不再被誤判為系統故障

- 可解碼但沒有可轉錄語音的音檔，終態為 `completed_no_speech`。
- `transcribe` 與 `timestamp` 回報 `not_applicable/no_speech_detected`。
- 來源仍保留，但不會產生可搜尋或可問答的假知識。
- 真正無法解碼、Provider 失敗或工作異常仍維持 `failed`。

### 1.4 執行環境可重現

每個終態 readiness 記錄非機密的 `input-runtime.v1`：

- release ID、source commit、schema head 與映像識別；
- OS、Python 版本與機器架構；
- ffmpeg、ffprobe、Tesseract、pdftotext、LibreOffice 是否存在及版本；
- OpenAI、pytesseract、Pillow、pypdf、openpyxl 套件版本；
- 對上述內容計算 SHA-256 identity hash。

不收錄 API key、密碼、連線字串或環境變數全文。

### 1.5 UI 呈現

資產詳情頁不再只列出英文 capability 名稱，而會顯示繁體中文能力名稱、實際狀態、原因、Provider／模型及產出數量。Provider 未供應 confidence 時會明示：

> 信心度：供應商未提供（不是 0%）

舊工作若尚未有新契約，介面顯示「尚未回報」，不臆測為成功。

### 1.6 既有資料修復

新增 migration：`input_i10_confidence_001`。

修復範圍只包含已知舊行為：`core.video`、版本 `1.0`、`transcript_segment`、confidence 為 0 且尚未聲明 confidence 語意的資料。修復後改為 `null` 並標記歷史 Provider／模型資訊；其他 Provider 的真正零分不會被修改。

另對舊版長音檔逐字稿補上「原本就是未知信心」的 metadata，但不改寫其 `null`，也不碰真正的實測零分。

跨租戶資料修復若遇到 FORCE RLS，migration 必須先驗證資料庫身分具有 `BYPASSRLS`／superuser 或 `enclave_rls_bypass` marker role；非 FORCE RLS 僅允許實際 table owner。通過後先寫入 `platform_maintenance_audit`，marker role 再於同一 transaction 開啟 bypass。未授權身分會直接中止。

## 2. Code Review 發現與修正

| 發現 | 風險 | 修正 |
|---|---|---|
| Provider 未回傳 confidence 卻用 0 當 sentinel | 使用者誤以為辨識品質為 0%；真零分與未知無法區分 | 型別改為 nullable，另存 provider-supplied 與 calibration 語意 |
| 工作只回報總體成功／失敗 | 部分能力缺產物仍可能看似成功 | 新增逐 requested-capability 四態契約；漏報 fail closed |
| 無語音被丟成處理例外 | 合法空內容被錯誤要求重試 | 改為完成但不可搜尋的 `not_applicable/no_speech_detected` |
| 失敗工作沒有逐能力結果 | 使用者與維運人員不知道失敗範圍 | orchestrator failure 自動補齊每項能力結果 |
| 文件有文字就宣稱版面／表格品質完整 | 機械成功被誤當語意品質通過 | 尚無 fidelity ground truth 時標記 degraded，不過度宣稱 |
| 新增 provenance metadata 會改變 artifact hash | 舊工作重試可能建立重複候選 | 以內容與穩定時間／畫面 locator 相同比對歷史 artifact，維持冪等 |
| 跨租戶 migration 在 FORCE RLS 下可能更新 0 筆 | 部署顯示成功但資料未修到 | 增加經角色驗證且有稽核紀錄的 migration bypass |
| Provider error 原文可能進 capability details | 外部錯誤可能含不應展示的資訊 | readiness 只保留失敗 Provider 名稱，不保存原始錯誤全文 |
| downgrade 直接刪 provenance 欄位 | 可能刪除 migration 前已存在的資訊 | rollback 只移除本契約標記，保留 provenance |
| 無文字影片的 OCR 仍宣稱 Provider 已供應信心 | 使用者會誤認為系統曾收到可比較分數 | 無文字時明確回報 `not_applicable`、未供應 confidence、無 calibration |
| 任務終態用全域設定冒充實際 Provider／模型 | 切換 Provider 或版本後，證據無法重現 | 終態一律使用實際 `TranscriptionResult`／`VideoProcessingResult` 身分 |
| runtime probe 可能序列等待或解碼失敗 | 第一次錯誤落庫反而被環境探測拖慢／阻斷 | native tool 探測改為並行、單項 3 秒上限，解碼與程序錯誤 fail closed |
| cached runtime identity 可被呼叫端修改 | 後續工作可能保存被污染的環境證據 | cache 僅留在私有來源，所有呼叫取得深拷貝 |
| 歷史 capability payload 損壞會阻斷新錯誤落庫 | 真實失敗無法保存，工作停在假狀態 | failure path 逐項驗證；壞舊值改以本次 failure reason 重建 |
| 文件切片為空直接 return | job／asset 可能持續顯示 running／processing | 文件、revision、job、asset 同步進入明確 failed 終態 |
| 空白試算表被包成一個空 chunk | 無內容來源可能被標記完成 | 空白內容回傳零 chunks 並走不可重試的 no-usable-content 終態 |
| Embedding 回傳數少於 chunks 時 `zip` 靜默截斷 | 部分內容遺失但工作仍顯示成功 | 寫入前強制 chunks 與 embeddings 1:1，否則整體失敗重試 |
| 文件重試只用本次新增量覆寫 chunk_count | 已有 chunks 的 retry 可能把計數改為 0 | 終態改查該 document revision 的持久化總數 |
| 同批文件重複 chunk 未更新 in-memory hash | 同一任務可能撞 unique index | 每次 add 後立即加入 hash set，維持批內與跨重試冪等 |
| 文件內層 `self.retry()` 又被外層 `Exception` 捕捉 | 同一錯誤可能建立雙重 retry 控制流 | 外層明確讓 Celery `Retry` 原樣拋出，只重試一次 |
| 文件 job、revision 與 SourceAsset 狀態未同步 | UI 可能同時看到 active、running、failed 等矛盾狀態 | 起始、覆核、完成、重試等待與耗盡失敗均同步 canonical state |
| 音檔重試只計算本次 artifact_ids | 部分已落庫內容可能在下次被誤判為無語音 | 重試先載入該 revision 已持久化逐字稿，再合併本次結果 |
| Provider technical error 透過影片 projection 進入 readiness | UI／API 可能曝光外部服務細節 | user-visible readiness 只留 Provider 與受影響能力；技術錯誤只留治理 artifact |
| 雲端 OCR 接手仍保留前一解析器 confidence | 新文字被套用不相關分數，形成資料層假象 | 接手後 confidence 設為 `null`、標示 unknown 並強制人工確認 |
| Docling 啟用時在 native metadata 建立前就寫入 | 成功的 Docling 可能因未初始化變數被吃掉，實際永遠無法採用 | 先獨立保存 Docling metadata，選中後才合併；無可信分數時設 unknown 並要求確認 |
| 前端相信 TypeScript 型別，不驗證歷史 JSON | 壞 payload 可能顯示空標籤或造成畫面錯誤 | runtime guard fail closed 顯示「狀態資料無法辨識」 |

Review 結論：第二輪嚴格檢視確實找到多項第一輪未覆蓋的真實缺陷，以上均已修正並補測。目前未發現仍阻擋 I10-2 本地合併的已知程式缺陷；正式環境與 PostgreSQL migration Gate 尚未執行，因此不得把本結論解讀為正式站已驗收。

## 3. 驗證證據

### 自動測試

- Python focused regression：`181 passed`。
- 涵蓋 capability 四態、未知與實測零分、壞歷史 payload、失敗工作、RLS migration 授權、文件空內容與 embedding 完整性、文件／資產狀態、影片冪等、影音處理、雲端 OCR fallback 及既有語音產品層。
- Frontend Vitest：`4 passed`。
- TypeScript：`tsc --noEmit` 通過。
- Ruff：通過。
- `py_compile`：通過。
- `git diff --check`：通過（僅 Windows LF/CRLF 提示，無 whitespace error）。
- Alembic：單一 head `input_i10_confidence_001`。

### 擴大回歸限制

擴大回歸中，可執行測試持續通過；依賴本機 PostgreSQL 的案例仍因 `localhost:5435` 未啟動而 `connection refused`。例如產品層批次為 `101 passed / 3 infrastructure blocked`，另一批 parse／phase gate 為 `123 passed / 2 infrastructure blocked`。這些不是 assertion regression，但也不得被換算成 PASS。Docker Desktop daemon 同樣未啟動，因此本輪無法補跑 PostgreSQL integration suite；部署前仍須在 release 環境執行 migration 與 PostgreSQL integration gate。

## 4. 尚未完成且不得混淆

- 本 Phase 尚未部署到 `kachu.tw`，正式資料 migration 尚未執行。
- 尚未以李永仁身分做瀏覽器旅程；目前環境沒有可控制的登入瀏覽器，且沒有其現行密碼。
- OCR 多路 fallback、繁中 locale 正規化及 terminology hint 屬 I10-3。
- 來源層級確認、低風險建立者權限與移除技術 artifact 待辦屬 I10-4。
- KnowledgeUnit 發布、Ask 命中與引用真實 Gate 屬 I10-5。
- S1／S2 ground truth corpus 與正式泛化驗收仍為 HOLD。

## 5. 發布 Gate

I10-2 要進正式環境前必須：

1. 在具授權 migration role 的 release 環境執行 Alembic upgrade。
2. 驗證修復筆數只落在已知 0 sentinel 範圍，並確認 maintenance audit 有紀錄。
3. 確認 API、document worker、media worker 使用同一 release identity。
4. 上傳至少一筆有語音、一筆無語音、一筆無文字畫面及一筆損壞來源，核對四態結果。
5. 驗證 UI 顯示未知 confidence 而非 0%，並確認實測零分仍能保留。

完成以上 release gate 前，本文件只支持「I10-2 本地實作與 code review 通過」，不支持「正式環境已修復」。
