# Enclave Input Platform 能力地圖與實作計畫

> 文件狀態：Architecture Decision / Implementation Authority
> 基準日期：2026-08-28
> 適用範圍：多租戶平台、Enterprise Knowledge Kernel、Multimodal Ingestion Fabric、Input UI
> 不涵蓋：各部門場景功能的新增需求，除非該功能是驗證 Input 核心能力所必需

---

## 1. 決策摘要

Enclave 接下來的第一產品優先級，是把「多元 Input」做成傳統製造業可信賴的共同入口：

1. **可靠**：資料不遺失、不重複、不假完成；失敗可理解、可重試、可續傳、可追溯。
2. **快速**：上傳與處理解耦，先接收、後處理；批次、長檔與弱網不阻塞使用者。
3. **易用**：文件、表格、圖片、錄音、影片、網址與外部來源使用同一心智模型，盡量自動辨識與補齊 metadata。
4. **可治理**：原檔、版本、租戶、部門、權限、密等、證據座標與人工覆核從入口即建立。
5. **可組裝**：Input 與 Knowledge Kernel 是平台核心；MKA 與未來產、銷、人、發、財應用只能依賴核心，核心不得反向依賴場景模組。

這個方向與目前模組化架構一致，但目前只能判定為「核心骨架已建立、Input 產品化尚未完成」。在本計畫的 Pilot Gate 通過前，不應宣稱所有格式、長時間媒體、行動裝置與工廠網路都已達商用品質。

---

## 2. 為什麼這是傳產製造業的第一優先級

製造企業的重要知識通常不是單一乾淨文件，而是散落在：

- PDF、Word、Excel、CSV、簡報、掃描表單與手寫註記；
- 機台銘牌、白板、品檢照片、異常照片；
- 訪談、交班、會議與老師傅口述；
- 開機、換線、保養、故障排除與巡檢影片；
- NAS、共用資料夾、雲端硬碟、網址與既有系統紀錄。

若入口不可靠，後續檢索、SOP、訓練、品質、維修與決策應用只會放大錯誤。反過來，只要同一份可信資料能被正確接收、解析、授權、引用與版本化，就能被不同職能模組重複使用。因此 Input 不是附屬功能，而是企業知識產品的供應鏈入口。

---

## 3. 架構邊界與依賴規則

```text
Tenant / Identity / Policy
          ↓
Input Experience
  ├─ upload / batch / capture / URL / connector
  ├─ transfer session / resume / checksum / progress
  └─ classification / ACL / context
          ↓
Multimodal Ingestion Fabric
  ├─ adapter routing / lifecycle / retry
  ├─ parse / OCR / ASR / video analysis
  └─ confidence / degradation / review routing
          ↓
Enterprise Knowledge Kernel
  ├─ SourceAsset / AssetRevision / DerivedArtifact
  ├─ EvidenceSpan / KnowledgeUnit / Release
  └─ search / citation / version / governance
          ↓
Workflow Kernel
          ↓
Domain Packs and Tenant Solutions
```

必須遵守的依賴規則：

- Input 核心不得匯入 MKA 或其他 Domain Pack。
- 長時間錄音、照片／影片擷取、續傳與離線佇列屬於 Input 核心。
- 場景模組可以提供欄位模板、抽取 schema、覆核流程與輸出格式，但不得建立另一套資產身分、權限或證據模型。
- 所有來源最終都必須收斂到 `SourceAsset → AssetRevision → DerivedArtifact / EvidenceSpan → KnowledgeUnit`。
- Legacy `Document` 可以在相容期存在，但不得成為新增來源唯一或最終身分。

---

## 4. 證據等級

本文件只使用以下四種狀態，避免把「有程式碼」誤寫成「已可商用」：

| 狀態 | 定義 |
|---|---|
| **A — 已實作且內部驗證** | 有正式路徑與自動化測試，可在已定義的內部範圍重現 |
| **B — 已實作，環境驗證待完成** | 程式與測試存在，但真實 provider、實體裝置、客戶資料或正式負載尚未證明 |
| **C — 部分／過渡狀態** | 路徑可用，但有 legacy 依賴、UX 缺口、能力不一致或失敗復原不足 |
| **D — 未實作** | 尚無完整產品路徑，或只有構想／schema |

狀態 A 也只代表已列出的驗證範圍；沒有任何 A 狀態可以自動推論為所有檔案、所有裝置、所有語言或所有產線都成立。

---

## 5. 目前 Input 能力地圖

### 5.1 共用底座

| 能力 | 現況 | 狀態 | 主要缺口 |
|---|---|---:|---|
| 統一資產身分與版本 | 已有 `SourceAsset`、`AssetRevision`、`DerivedArtifact`、`EvidenceSpan` | A | 部分文件與 Connector 仍先經 Legacy `Document` 投影 |
| 統一 ingestion job | 有 adapter routing、狀態機、事件序列、重試與 readiness | A | 尚缺跨 adapter 的完整操作 SLO 與大量實檔證據 |
| 租戶與密等 | 建立資產時帶 tenant 與 data classification | A | Input UI 尚未完整呈現部門／ACL／現場情境；正式共享資料庫 hard isolation 尚未完成 |
| 雜湊與去重 | 以 SHA-256 建立內容識別與 deduplication | A | 前端沒有先算 hash，弱網重送仍可能重傳完整檔案 |
| Idempotency | 後端支援 idempotency key | C | 統一 Input 前端尚未穩定產生、保存與重用 key |
| 檔案掃描 | 文件、音訊、影片上傳路徑有掃描整合 | B | 正式環境掃描 provider 啟用狀態與 fail-closed 行為需驗證 |
| 非同步處理與背景任務 | 上傳後可背景處理，前端可記住 task | A | 尚缺統一的 queue center、取消、暫停、優先序與跨裝置狀態 |
| 失敗透明度 | job 有 failed/review_required/ready 等狀態與錯誤欄位 | A | UI 需提供可執行的原因、重試範圍與降級結果說明 |
| 通用續傳 | 長訪談有 chunk；一般檔案沒有 upload session/multipart resume | D | 是長音訊、影片、弱網與行動裝置的首要阻塞 |

### 5.2 來源別能力

| Input 類型 | 已有入口與處理能力 | 狀態 | 尚未關閉的缺口 |
|---|---|---:|---|
| PDF / DOCX / TXT | 統一上傳、文字／版面／表格解析；PDF 有 OCR fallback | A/C | 文件仍經相容投影；真實複雜版面、超大檔與掃描品質需擴大 corpus |
| DOC / RTF / HTML / MD / JSON | 後端 parser 已支援 | C | `/knowledge/new` 未列入 accept；各格式測試深度不一，不能只因 parser 存在就全面開放 |
| PPT / PPTX | 後端 parser 已支援 | C | UI 未開放；圖文關係、speaker notes、圖表與頁面證據精度需驗證 |
| XLS / XLSX / CSV | 工作表、表格與列資料解析 | A/C | UI 只明示 XLSX/CSV；公式、合併儲存格、大型活頁簿、隱藏頁與 cell evidence 需 golden corpus |
| JPG / JPEG / PNG | 圖片上傳、OCR、bbox evidence | A/B | 實際低光、傾斜、髒污、手寫與銘牌資料待驗證；fallback bbox 可能只是整張圖 |
| TIFF / BMP / WEBP / HEIC | 後端 parser 有對應能力 | C | UI 未開放；手機 HEIC、multi-page TIFF 與 OCR provider matrix 待驗證 |
| 音訊檔 | MP3/WAV/M4A/OGG/FLAC 上傳、ASR、時間碼、術語修正 | B | 真實工廠噪音、多人、台語／中英混用、長檔、provider 與成本／速度未完成驗收 |
| 長時間瀏覽器錄音 | 分段錄製、IndexedDB 離線佇列、create/chunk/complete/retry | B/C | 能力仍位於 MKA；尚未成為 `/knowledge/new` 的核心能力，實體手機鎖屏／切 App 未證明 |
| 影片 | metadata、demux、ASR、關鍵幀、OCR、場景、跨模態時間軸與候選知識 | B | 單次上傳無續傳；真實長片、codec/device、產線噪音與動作／設備狀態準確度未證明 |
| 網址 | URL intake、SSRF 防護、資產與 ingestion job | B/C | 動態頁、登入頁、robots／授權、內容變更偵測與可引用座標需系統化 |
| 外部 record / API | `source_record_id` 與 capture manifest 入口存在 | C | 缺標準 connector SDK、source cursor、ACL 映射與一致 retry contract |
| NAS / SMB | 本地／UNC 掃描、hash、resource/ACL、delta 基礎 | B | rename/delete、權限映射、衝突、超大樹與正式客戶 NAS 長時間同步需驗證 |
| SharePoint / Google Drive | schema、OAuth／整合路徑存在 | B | 未以客戶 tenant 與真實權限完成認證，不能宣稱 GA |
| Email mailbox | parser 可處理 email 類型的內容概念 | D | 沒有已驗證的 mailbox connector、thread/attachment/ACL/retention 產品路徑 |
| 資料夾／大量匯入 | UI 可多檔，Connector 可掃描 | C | 無 folder manifest、目錄階層保留、整批政策預檢、批次續傳與批次錯誤處理 |

---

## 6. 目前 UI/UX 判定

`/knowledge/new` 與 `/knowledge/assets` 已建立統一入口與統一資產庫，方向正確，但尚未形成傳產現場所需的完整 Input Experience。

### 已成立

- 檔案、網址與外部紀錄共用同一新增知識入口。
- 多檔佇列提供 pending / uploading / done / error 與進度。
- 支援圖片、音訊、影片的行動裝置 capture attribute。
- 任務可在背景繼續，瀏覽器可記住部分 task。
- 使用者不需要先理解每一個 parser 或後端 adapter。

### 必須重構或補強

1. **格式能力單一來源**：前端 accept 清單少於後端 parser。支援格式、大小、時間、codec 與 tenant policy 應由 capability API 回傳，不可前後端各自硬編碼。
2. **上傳前預檢**：加入格式、大小、影片時長、網路、重複檔案、可用配額與權限預檢，避免傳完才失敗。
3. **可復原佇列**：每個項目要能暫停、取消、續傳、重試；重新整理、斷網、登入逾時與應用切換後不得遺失已確認的 chunk。
4. **情境 metadata**：入口要能用最少輸入取得廠區、產線、機台、產品、部門、角色與密等；可由租戶模板、QR code 或檔案路徑自動帶入。
5. **核心長錄音**：把 MKA 的長時間錄音與 IndexedDB queue 下沉為平台元件，MKA 改成消費者。
6. **真實狀態**：明示「已接收」「分析中」「可搜尋」「待覆核」「部分完成」「失敗」，不得以單一完成圖示掩蓋降級或缺漏。
7. **批次操作**：提供資料夾匯入、整批套用 metadata／ACL、錯誤篩選與只重試失敗項目。
8. **行動現場模式**：大按鈕、低輸入、可戴手套操作、弱網提示、裝置空間提示、不中斷錄製的清楚限制與替代方案。

---

## 7. 關鍵差距排序

| 優先級 | 差距 | 為何先做 |
|---:|---|---|
| P0 | 通用 upload session、分段續傳、checksum commit | 沒有它，長音訊／影片與工廠弱網無法可靠產品化 |
| P0 | Input contract 與 capability API 前後端一致 | 直接消除「後端支援但 UI 不支援」與錯誤宣稱 |
| P0 | 核心化長時間錄音／離線佇列 | 這是通用 Input，不應被任何場景 Pack 綁住 |
| P0 | 真實裝置、弱網、噪音與長檔驗證 | 現有測試主要證明程式 contract，尚未證明現場可用性 |
| P1 | 統一資產直寫，逐步移除 Legacy `Document` 前置依賴 | 降低雙模型維護與狀態不一致風險 |
| P1 | 批次／資料夾／NAS delta 與 ACL | 製造企業導入通常不是逐檔上傳 |
| P1 | OCR／ASR／表格 golden corpus 與 confidence calibration | 決定知識檢索與引用品質，不可只看成功率 |
| P1 | Intake telemetry、SLO、queue fairness、cost guardrails | 正式容量測試曾豁免，目前沒有商用規模證據 |
| P2 | SharePoint／Drive 客戶 tenant 認證 | 需外部 credentials，可在核心可靠性建立後驗證 |
| P2 | Mailbox 與更多 connector | 重要但不應先於共用 transfer／asset contract |

---

## 8. 產品不變量

以下條件應寫入 API contract、測試與 Code Review checklist：

1. 原始檔一旦成功 commit 必須不可變；修訂建立新 `AssetRevision`。
2. 伺服器未確認的 bytes 不得被 UI 宣稱已保存。
3. 同一 idempotency key 與相同內容不得建立重複資產；衝突必須明示。
4. 解析、OCR、ASR 或影片分析失敗，不得抹除已安全接收的原檔。
5. 所有衍生知識必須能回到資產、版本與 evidence locator。
6. 低信心或正式 SOP 衝突必須進入覆核，不得靜默發布。
7. 權限與密等從 Input 開始繼承；衍生物不得比來源更寬鬆。
8. 可選 Pack 關閉時，核心上傳、錄音、處理與檢索仍可運作。
9. provider 降級、未啟用或超出配額時，必須回報真實 readiness 與原因。
10. 刪除、保留期限、legal hold 與 Connector source deletion 必須有明確策略，不得由同步程式自行猜測。

---

## 9. 驗收指標

下表是**目標 gate，不是目前 production 成績**。每一項需由封存報告、dashboard export 或可重放測試證明。

| 面向 | 目標 |
|---|---|
| 接收確認 | 檔案傳輸 commit 完成後，資產 ledger acknowledgement p95 ≤ 2 秒 |
| 資料完整性 | sealed corpus checksum mismatch = 0；silent loss = 0 |
| 去重／冪等 | 相同內容與 idempotency replay 的非預期重複資產 = 0 |
| 續傳 | 斷線、重新整理或重新登入後，不重傳已由伺服器確認的 chunk |
| 狀態透明 | 100% job 可區分 accepted / processing / review / ready / partial / failed |
| 權限 | 100% 資產與衍生物具有 tenant、classification 與可計算 ACL |
| 證據 | 100% 可發布 Knowledge Unit 具有可解析的 source/version/evidence locator |
| 低信心治理 | 100% 低於政策閾值的輸出進 review 或明示降級，不自動發布 |
| 行動裝置 | 支援裝置／瀏覽器矩陣的 capture-to-accepted 成功率 ≥ 95% |
| 弱網 | 定義網路 profile 下，恢復成功率 ≥ 99%，且無整檔重傳 |
| 批次 | 10,000 檔 manifest 能呈現逐檔結果、只重試失敗項目且不重複成功項 |
| 可觀測性 | 每一 ingestion job 可由 asset、tenant、adapter、provider、attempt 與 trace 查詢 |
| 租戶公平性 | 單一租戶高負載不得使其他租戶越過已定義的 latency/error budget |

解析品質不使用單一「準確率」概括。每種格式需各自定義：文字召回、表格結構保真、OCR 字元／欄位準確率、ASR WER／關鍵術語召回、speaker/timecode error、影片 evidence alignment error，以及人工覆核率。

---

## 10. 分階段實作計畫

所有 Phase 都遵守同一節奏：

```text
實作 → 自動化測試 → 風險與相容性檢查 → 獨立 Code Review → PASS 才進下一 Phase
```

Code Review 結果只允許 `PASS`、`PASS WITH FOLLOW-UP` 或 `HOLD`。涉及資料遺失、租戶越權、假完成、不可復原 migration 或未封閉的核心依賴時一律 `HOLD`，不得進下一階段。

### Input I0 — Contract 與證據凍結

**目的**：先建立唯一事實來源，避免在不同 UI、adapter 與文件中持續分岔。

交付：

- 建立 Input capability registry：格式、MIME、大小、時間、codec、provider、tenant policy 與 degradation。
- 建立 API contract：asset、revision、upload session、job、artifact、evidence 與 review state。
- 建立涵蓋文件、表格、圖片、音訊、影片與失敗樣本的 sealed golden corpus manifest。
- 建立 production telemetry baseline；明示 P5 waived 項目仍未驗證。
- 標記 `CAPABILITY_CLAIMS.md` 與 `PIPELINE_STRENGTH_MAP.md` 的歷史時點，避免其舊數字被當成現況。

測試／證據：contract tests、schema snapshot、capability parity test、golden corpus hashes、baseline report。

Review gate：前後端、文件與 runtime capability 無未說明差異；所有宣稱可追到證據。

**2026-08-29 狀態：`PASS`。** 已建立 `input-capabilities.v1` server-owned registry、authenticated discovery API、runtime contract snapshot、sealed corpus manifest 與 telemetry baseline；72 項擴大回歸全部通過。Code Review 見 `PHASE_INPUT_I0_CONTRACT_EVIDENCE_CODE_REVIEW_2026-08-29.md`。此段保留 I0 當階段證據；最新總進度以本文件結論為準。

### Input I1 — Intake Contract 與 UX 收斂

**目的**：讓單一入口正確呈現能力與政策，先解決錯誤期待與重複提交。

交付：

- `/knowledge/new` 改由 capability API 產生 accept、限制與提示。
- 前端建立並持久化 idempotency key，重試沿用同一 key。
- 加入上傳前格式、大小、時長、codec、配額與重複檢查。
- 提供 classification、department/ACL 與廠區／產線／機台等可設定 metadata。
- 每檔具備取消、重試、錯誤原因與狀態明細；批次可套用共同 metadata。
- capability summary 依 runtime/provider 真實狀態顯示，不寫死「一定可 OCR／轉錄」。

測試／證據：frontend contract/component/E2E、backend validation、idempotency replay、accessibility 與多語系測試。

Review gate：UI 不再接受後端拒絕的檔案，也不隱藏後端已正式開放的能力；重試不建立重複資產。

**2026-08-29 狀態：`PASS`。** `/knowledge/new` 已改由 `input-capabilities.v1` 產生 accept、格式／大小／影片時長／租戶配額與 degradation 提示；每檔 idempotency key 會以租戶隔離的 IndexedDB 草稿保存並在取消、刷新與重試後沿用。文件、音訊、影片與外部來源共用 classification、department ACL 及廠區／產線／設備等 allowlisted context metadata，canonical asset 與 ingestion job 在派送前完成一致建立。最終回歸為 backend 105 passed、frontend 32 files／110 passed、Playwright Chromium 2 passed、TypeScript／ESLint／production build PASS。Code Review 見 `PHASE_INPUT_I1_INTAKE_UX_CODE_REVIEW_2026-08-29.md`。此段保留 I1 當階段證據；I2 的完成狀態記錄於下一節。

### Input I2 — 通用續傳與弱網可靠性

**目的**：建立所有大型檔案與 capture 都能共用的可靠 transfer layer。

交付：

- upload session：init、chunk/part、checksum、commit、abort、expire、resume。
- object storage multipart adapter 與本地開發 adapter，行為由同一 contract 約束。
- chunk acknowledgement、重試退避、並行度、流量限制與過期清理。
- IndexedDB-backed queue；重新整理、斷網與重新登入後恢復。
- 已 commit 原檔與 ingestion job 解耦；處理失敗不要求重新上傳。

測試／證據：property/fuzz tests、network fault injection、browser reload、auth expiry、duplicate/out-of-order chunk、checksum corruption、large-file E2E。

Review gate：零 silent loss；已確認 chunk 不重傳；跨租戶 session 猜測與越權測試全部阻擋。

**2026-08-29 狀態：`PASS`。** 已建立 tenant/owner-scoped `upload_sessions`／`upload_parts` 與 RLS migration，提供 init、status/resume、part、commit、abort、expire API；每個 part 由瀏覽器計算 SHA-256，伺服器限制預期長度並重算 checksum，重送相同內容為冪等、不同內容 fail-closed。`StorageBackend` 已加入 local 與 S3/R2/MinIO-compatible native multipart contract，commit materialize 後仍只走 canonical `/knowledge/assets` intake，不另建資產權威。`/knowledge/new` 以三路並行、指數退避、IndexedDB session id 與 acknowledged part 狀態支援暫停、刷新及重新登入續傳；定時維護工作會中止／刪除過期 staging。驗證涵蓋 out-of-order、duplicate、checksum corruption、missing part、跨使用者與跨租戶猜測、過期、12 MB 多分塊 E2E、隨機 multipart property、migration fresh upgrade/downgrade/re-upgrade，以及 Chromium 401 後只補傳缺塊。Code Review 見 `PHASE_INPUT_I2_RESUMABLE_UPLOAD_CODE_REVIEW_2026-08-29.md`。實際客戶 S3/R2/MinIO endpoint、工廠網路及實體行動裝置仍屬部署環境驗證，不影響 I2 內部程式碼 gate；Input I3 entry 已開放。

### Input I3 — Core Capture 平台化

**目的**：把錄音、拍照與錄影從特定場景抽成共用 Input 能力。

交付：

- 將 `LongInterviewRecorder`、chunk queue 與 capture APIs 移入平台 Input 模組。
- `/knowledge/new` 提供長錄音、拍照、短片／影片擷取，並共用 I2 upload session。
- MKA 改為使用 core capture public API，不再持有底層實作。
- 明示 microphone/camera consent、錄製中狀態、裝置空間、鎖屏／切 App 限制與中斷復原。
- 支援租戶設定的時間上限、保留政策、預設 metadata 與術語表。

測試／證據：dependency boundary、component/E2E、iPhone Safari、Android Chrome、desktop browser、permission denied、incoming call/app switch/lock screen 測試矩陣。

Review gate：關閉 MKA 後仍能完成 capture-to-asset；實體裝置報告具備可重現版本與媒體樣本 hash。

**2026-08-29 狀態：`INTERNAL SOFTWARE PASS / DEVICE CERTIFICATION PENDING`。** Capture API、`CoreAudioRecorder` 與 IndexedDB queue 已提升為 core Input；MKA 僅保留 adapter。`/knowledge/new` 可長錄音、拍照與錄影，照片／影片沿用 I2，錄音建立 canonical audio asset；tenant policy、consent、裝置空間、page hidden flush、治理 metadata 與術語快照均已完成。Backend 46 passed、frontend 34 files／118 passed、四種 Chromium 桌面／行動尺寸 E2E、TypeScript／ESLint／Ruff／production build 與 I3 migration round-trip 均 PASS。iPhone Mobile Safari、Android Chrome 與鎖屏／來電／網路切換仍缺實機樣本 hash，因此依原 review gate 暫不開放 I4。Code Review 見 `PHASE_INPUT_I3_CORE_CAPTURE_CODE_REVIEW_2026-08-29.md`。

### Input I4 — 文件、表格、圖片品質工程

**目的**：以製造業資料而非一般示例證明解析品質。

交付：

- 依 sealed corpus 分批開放 DOC、XLS、PPTX、TIFF、HEIC 等 UI 格式。
- 建立 SOP、檢驗表、料號表、BOM、設備手冊、掃描表單、銘牌與手寫註記 corpus。
- 保留頁、段、sheet、cell/row、bbox 與版面關係；明示 whole-image bbox fallback。
- OCR 旋轉、低光、污損、多語與專有詞校正；表格公式／合併儲存格／隱藏頁政策。
- provider fallback、confidence calibration 與人工覆核 sampling。

測試／證據：格式別 quality report、regression corpus、provider drift replay、evidence locator round-trip。

Review gate：每個 UI 開放格式均有品質門檻與失敗樣本；不得以「解析成功」替代內容正確性。

**2026-08-29 狀態：`INTERNAL PASS`。** 已建立格式別品質門檻、製造業形狀 sealed corpus、native provider drift replay、段落／投影片／row-cell／OCR bbox evidence、whole-image fallback 覆核、旋轉／低光／多頁 TIFF 與 Excel 公式／合併／隱藏頁政策。UI 開放格式全具 PASS 品質報告與 deliberate failure sample；PPTX／TIFF 新增內部開放，DOC／XLS／HEIC 仍關閉。Backend 58 passed、frontend 34 files／119 passed、TypeScript／ESLint／Ruff／production build、migration round-trip 全部 PASS。詳細 Code Review 見 `PHASE_INPUT_I4_DOCUMENT_IMAGE_QUALITY_CODE_REVIEW_2026-08-29.md`。

### Input I5 — 音訊與影片產品化

**目的**：完成真實長媒體、工廠噪音與時間軸證據驗證。

交付：

- 長音訊／影片使用 I2 續傳，提供背景處理進度、preview/proxy 與 partial readiness。
- 驗證 MP3/WAV/M4A/OGG/FLAC 與 MP4/MOV/WEBM/MKV 的實際 device/codec matrix。
- 建立機台噪音、多人交談、口音、術語、靜音、低品質收音與長影片 corpus。
- 驗證 ASR speaker/timecode、scene、keyframe/OCR、audio-event 與跨模態 evidence alignment。
- 動作、設備狀態與異常聲音維持「候選」語意，未通過 corpus 前不得自動成為正式事實。
- 建立 SOP conflict check 與人員覆核工作台的完整證據鏈。

測試／證據：real-media golden run、時軸誤差報告、device/codec matrix、24h queue/degradation run、安全與隱私檢查。

Review gate：長檔失敗不要求重傳；所有發布內容可跳回正確時間點／畫面；低信心與衝突不自動發布。

**2026-08-29 狀態：`INTERNAL ENGINEERING PASS / EXTERNAL MEDIA CERTIFICATION PENDING`。** 長音訊已改為 bounded chunk、逐段 checkpoint 與 partial readiness；音訊／影片皆有 tenant-scoped browser proxy，影片具分階段進度、worker re-probe、exact-time evidence、SOP conflict 與人工發布 gate。實際 synthetic-signal codec corpus 的 MP3/WAV/M4A/OGG/FLAC 與 MP4/MOV/WEBM/MKV 為 9/9 PASS，duration timeline mean error 3.06 ms、max 24 ms。Backend related 123 passed、frontend 34 files／119 passed、TypeScript／ESLint／Ruff／production build與 migration round-trip PASS。實體裝置、合法工廠人聲／口音 ground truth 與 24h live queue campaign 仍 pending；不得視為商用媒體準確率或 SLA。Code Review 見 `PHASE_INPUT_I5_AUDIO_VIDEO_PRODUCTIZATION_CODE_REVIEW_2026-08-29.md`。

### Input I6 — Connector 與大量匯入

**目的**：讓企業既有資料可以受控、大量且持續地進入同一資產模型。

交付：

- NAS/SMB delta sync：新增、修改、rename、delete/tombstone、ACL 與 cursor/reconciliation。
- folder/batch manifest：階層、共同 metadata、逐檔結果、只重試失敗項目。
- Connector 直接 materialize canonical Asset/Revision，逐步淘汰 Legacy `Document` 前置路徑。
- 標準 Connector SDK：discover、fetch、checksum、cursor、ACL、rate limit、retry、delete semantics。
- 有客戶 credentials 時，完成 SharePoint／Google Drive tenant 與 ACL 認證；否則維持 B 狀態。

測試／證據：large tree、rename/delete、permission drift、rate limit、token expiry、reconciliation、customer sandbox report。

Review gate：同步可重放且不重複；source deletion 不會未經政策直接不可逆刪除知識資產；ACL 不放寬。

**2026-08-29 狀態：`INTERNAL ENGINEERING PASS / CUSTOMER CLOUD CERTIFICATION PENDING`。** NAS/SMB 已具 deterministic complete/partial snapshot、cursor、rename/delete tombstone 與 ACL replacement；Connector 已 canonical-first materialize Asset/Revision，並以 replayable batch manifest 保存逐檔結果與 failed-only retry。標準 SDK 的 rate limit、token refresh 與 delete semantics 已完成。55 項相關測試、1000 檔 large-tree profile、Ruff、compileall 與 PostgreSQL migration round-trip PASS。SharePoint／Google Drive 因無客戶 credentials 維持 PENDING，不得宣稱已認證。Code Review 見 `PHASE_INPUT_I6_CONNECTOR_BULK_IMPORT_CODE_REVIEW_2026-08-29.md`。

### Input I7 — 容量、成本與營運韌性

**目的**：補回已豁免的正式負載證據，建立可承諾的產品邊界。

交付：

- 執行 P5 document upload、batch ingestion、audio queue、video queue profiles。
- 執行 degradation、provider outage、queue backlog、storage latency 與 soak campaign。
- 建立 per-tenant quota、queue fairness、backpressure、DLQ/reconciliation 與成本儀表板。
- 定義並量測 intake acknowledgement、transfer、queue wait、processing、review readiness SLO。
- 建立容量估算器與 onboarding 配額模板。

測試／證據：不可豁免的 live campaign report、dashboard exports、incident drill、cost report、runbook rehearsal。

Review gate：所有 P0/P1 SLO 有 live evidence；沒有無上限資源路徑；一個租戶的媒體 backlog 不拖垮其他租戶。

**2026-08-29 狀態：`INTERNAL CONTROL-PLANE PASS / LIVE CAPACITY GATE HOLD`。** 已完成 canonical job admission、per-tenant cap、global backpressure、round-robin selector、stale reconciliation／DLQ、五段 Input SLO metrics、成本 dashboard、容量估算與 onboarding quota template。64 項相關測試與 PostgreSQL migration round-trip PASS。Lite/Standard/Enterprise 2× live run、四種 live degradation 與 72h soak 尚未執行，權威 P5 verifier 因此維持 HOLD；依使用者既有 waiver 只准入 I8 Pilot 工具工程，不准入 GA／SLA／容量承諾。Code Review 見 `PHASE_INPUT_I7_CAPACITY_RESILIENCE_CODE_REVIEW_2026-08-29.md`。

### Input I8 — 第一租戶現場 Pilot Gate

**目的**：用真實人員、裝置、網路與資料證明產品，而不是把內部測試當市場驗證。

交付：

- 第一租戶使用專屬環境／資料庫與明確資料處理協議。
- 選定 2–3 個 Input journey，例如 NAS 批次、現場長錄音、機台影片。
- 建立租戶自有驗收集、術語表、metadata 模板、角色／ACL 與覆核責任人。
- 連續 2–4 週記錄成功率、重試、人工修正、處理時間、檢索引用與使用者摩擦。
- 對所有 incident、近失誤與未達 SLO 項目完成復盤。

測試／證據：signed acceptance、usage metrics、quality sample audit、security/permission audit、pilot retrospective。

Review gate：達成 agreed pilot SLO 且沒有未關閉的資料遺失、越權或假完成；通過才可討論擴租戶或 GA。

**2026-08-29 狀態：`ENGINEERING READY / FIELD PILOT NOT STARTED / GATE HOLD`。** 已完成 tenant-scoped Pilot evidence ledger、2–3 journey 設定、每日不可覆寫指標、incident／audit／retrospective、acceptance preflight、signed document hash/reference 與 `/system/input-pilot` 證據工作台。管理員可在產品內完成每日指標、Incident 建立／復盤結案、三類 Audit、整體復盤與客戶簽署，不再依賴手動 API。Gate 僅接受 live mode、14–28 天連續且每 journey 每日覆蓋的證據；最新品質／安全／權限 audit、所有 incident 復盤與最終客戶簽署缺一即 HOLD。I8 focused backend 9 passed、I6–I8 相關回歸 126 passed、完整 backend 1,500 passed／12 skipped、frontend 36 files／121 tests、TypeScript／ESLint／Ruff／production build、migration round-trip 均 PASS。跨階段 review 已補正 I6–I8 8 張新表 FORCE RLS 與 telemetry savepoint。真實第一租戶尚未開始，登入後人工視覺巡檢、14–28 天與簽署證據不存在；不得宣稱現場 Pilot 或 GA 已通過。Code Review 見 `PHASE_INPUT_I8_FIRST_TENANT_PILOT_CODE_REVIEW_2026-08-29.md` 與 `PHASE_INPUT_I8_PREPILOT_HARDENING_CODE_REVIEW_2026-08-29.md`。

---

## 11. 每個 Phase 的 Code Review 最低清單

- **Architecture**：依賴方向、canonical model、pack optionality、migration/rollback。
- **Tenancy & security**：tenant context、ACL/classification inheritance、session ownership、SSRF、malware、secrets、audit。
- **Reliability**：idempotency、checksum、retry、partial failure、timeout、cleanup、reconciliation、no silent loss。
- **UX/accessibility**：狀態用語、可執行錯誤、keyboard/screen reader、mobile/weak-network、localization。
- **Quality & evidence**：golden corpus、confidence、provider degradation、evidence locator、review routing。
- **Performance & cost**：bounded resources、quota、backpressure、tenant fairness、provider/storage cost。
- **Compatibility**：Legacy routes/data、API/schema compatibility、feature flag、rollback path。
- **Documentation & claims**：README、runbook、capability matrix 與 production claim 必須與實測一致。

每個 review 文件至少記錄 commit、schema revision、route hash、測試命令與結果、未解風險、waiver（若有）、結論與下一階段准入決定。

---

## 12. 實作邊界與暫緩項目

在 I0–I5 完成前，以下工作原則上暫緩：

- 新增與 Input／Knowledge 驗證無直接關係的大型部門場景。
- 為單一租戶複製另一套上傳、資產、權限、OCR、ASR 或知識模型。
- 在未建立 golden corpus 前大量開放 parser 支援格式。
- 把影片候選動作、設備狀態或異音描述當作已驗證診斷。
- 以更換模型或 provider 取代 transfer、治理、證據與覆核基本工程。

允許的例外是：某個小型場景能直接驗證 Input 核心，且以 Domain Pack 方式實作，不破壞核心依賴規則。

---

## 13. 與既有文件的關係

- `MODULAR_MULTIMODAL_KNOWLEDGE_PLATFORM_ARCHITECTURE.md` 仍是整體模組化架構權威。
- 本文件是 **Input Platform 現況、優先級、驗收與 I0–I8 執行順序的權威文件**。
- `PHASE_P3_MULTIMODAL_GOLDEN_CORPUS_CODE_REVIEW.md` 是目前多模態 canonical evidence 的既有證據，但不等於實體裝置／工廠 corpus 已驗收。
- `P5_CAPACITY_MODEL.md` 與 P5 waiver 仍有效；I7 要完成被豁免的 live validation。
- `P6_UIUX_DEVICE_CODE_REVIEW_2026-08-28.md` 證明瀏覽器層 contract 與 synthetic media，不證明實體手機與長時間媒體。
- `CAPABILITY_CLAIMS.md` 與 `PIPELINE_STRENGTH_MAP.md` 是歷史時點文件；涉及 Input 的現況判定若衝突，以本文件與較新的 sealed review evidence 為準，並於 I0 完成正式對帳。

---

## 14. 目前結論

Enclave 的產品方向已經是：

```text
多租戶治理
  + 多元 Input
  + Enterprise Knowledge Kernel
  + 可選場景模組
```

目前共用 Input 層 **I0–I8 內部工程已依序完成並經逐階 Code Review**；這不等於所有產品驗證 gate 已通過。I3 實體 iPhone／Android 認證、I5 真實工廠媒體、I6 客戶雲端 Connector、I7 live capacity／degradation／72h soak，以及 I8 第一租戶 14–28 天現場 Pilot 仍待外部證據。後續可開始受控首租戶導入，但在上述 gate 完成前不得宣稱共享多租戶 GA、SLA 或跨產業準確率。
