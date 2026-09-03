# Input I9：首租戶生產可靠性強化與持續問題紀錄

狀態：進行中

建立日期：2026-09-03

首個驗證租戶：八策股份有限公司

範圍：共用 Input、Knowledge、Review、Ask 核心；不包含選配場景應用模組

## 1. 文件定位

本文件是持續維護的生產問題與強化紀錄，不是一次性結案報告。後續任何租戶在文件、圖片、音檔、影片、網頁或 Connector 匯入流程發現問題時，都必須持續補入：

1. 使用者看到的症狀與時間。
2. 受影響的來源種類、裝置、格式及租戶範圍。
3. 技術根因及是否可能影響其他來源。
4. 暫時處置、永久修復及資料復原方式。
5. 單元、整合、瀏覽器、正式環境及租戶複測證據。
6. 修復 commit、部署 release、回滾點與未解風險。

「程式已修改」不代表問題完成。只有正式環境部署、既有資料修復及租戶複測通過後，問題才能標記為 `CLOSED`。

## 2. 2026-09-03 首租戶測試基線

李永仁以 iPhone Safari 操作正式網域 `kachu.tw`，當時首頁顯示 9 筆資產、2 筆可使用、1 筆處理中、140 筆待覆核及 2 筆失敗。

唯讀生產診斷確認：

- 兩支 WAV 均為標準 `pcm_s24le`，被音訊 codec allowlist 擋下；原始檔未損壞。
- 固定格式錯誤仍進行多次自動／人工重試，其中一筆工作 attempt 已達 9。
- 140 筆不是 140 個來源，而是 5 支影片的 138 個衍生候選，加上 1 個網頁來源的 2 個衍生候選。
- 「待覆核」與「待審核」均代表人工處置，但介面用詞不一致。
- 首頁以 `asset.status == active OR job.status == ready` 計算「可使用」，把仍在解析的圖片誤算為可使用；當時真正 answer-ready 的來源只有 1 筆。
- 圖片解析 Worker 遭 `SIGKILL` 後，資料庫工作持續停在 `running/parsing`，缺少孤兒工作回收。
- 部分影片建立瀏覽代理時亦曾因 `SIGKILL` 失敗；後續重試成功後，終態仍殘留舊錯誤內容。
- 網頁來源的文件 profile 已 answer-ready，但同一來源仍有兩個 `review_required` artifact，顯示發布與 artifact 覆核狀態需要統一說明及投影規則。

## 3. 問題台帳

| ID | 問題 | 嚴重度 | 狀態 | 完成條件 |
|---|---|---:|---|---|
| I9-001 | `pcm_s24le` WAV 無法處理 | P0 | VERIFIED | 正式環境可保留原檔、正規化、轉錄並進入人工確認 |
| I9-002 | 固定錯誤被重複重試 | P0 | VERIFIED | 永久錯誤不重試；暫時錯誤依策略退避重試 |
| I9-003 | 媒體工作超出 Worker 記憶體後遭 SIGKILL | P0 | VERIFIED | 媒體工作具資源隔離；代表性圖片與影片不再造成 WorkerLost |
| I9-004 | WorkerLost 後工作永遠停在處理中 | P0 | VERIFIED | 逾時工作可被偵測、標記並安全復原 |
| I9-005 | 「可使用」數字不等於真正可問答 | P0 | VERIFIED | 所有 UI 與 API 以單一 answer-ready 判定顯示 |
| I9-006 | 同一資產跨表狀態互相矛盾 | P0 | VERIFIED | source、revision、job、document、artifact、publication 投影一致 |
| I9-007 | 成功終態殘留舊錯誤 | P1 | VERIFIED | 成功／人工確認終態清除 active error，歷史保留在 event |
| I9-008 | 「待覆核／待審核」用詞不一致 | P1 | DEPLOYED | 全產品統一為「等待人工確認」，並說明責任人 |
| I9-009 | 140 個技術片段直接暴露給一般使用者 | P1 | VERIFIED | 先依來源分組，再展開例外或片段；支援適當批次處置 |
| I9-010 | 失敗頁只顯示通用訊息 | P1 | DEPLOYED | 顯示安全、白話、可採取行動的原因與追蹤代碼 |
| I9-011 | 狀態卡缺乏下一步 | P1 | DEPLOYED | 每個狀態可直接前往提問、人工確認、查看進度或處理問題 |
| I9-012 | 上傳相同檔案容易產生重複失敗來源 | P1 | OPEN | 內容雜湊去重與重送語意清楚，不重複計費或產生垃圾來源 |
| I9-013 | 第一方網頁 Input 被誤判為外部 Connector 而無法檢索 | P0 | VERIFIED | 網頁知識可由正式 Ask 命中並回傳來源引用；外部 Connector 仍維持 fail-closed |
| I9-014 | 正式 Redis 要求密碼但檢索快取未帶認證 | P1 | VERIFIED | 正式環境不再出現檢索快取認證失敗，且快取仍維持租戶／權限隔離 |
| I9-015 | 舊有完成文件缺少 lexical projection | P0 | VERIFIED | 既有文件完成受稽核且具租戶邊界的索引回填，關鍵字檢索可命中 |
| I9-016 | 共用 IMAGE_TAG 導致未變更 gateway 缺少部署標籤 | P1 | MITIGATED | 發布流程能保證所有 compose image 均有相同 release tag，部署前先驗證映像完整性 |
| I9-017 | 首租戶尚無 active KB revision 時 shadow scope 關閉所有問答 | P0 | VERIFIED | shadow 模式可讀取既有 answer-ready 文件並附引用；enforce 與無權 revision 仍 fail-closed |
| I9-018 | 首次圖片尚待人工確認卻提前列入已可問答 | P0 | VERIFIED | 首版待確認不列入可問答；已有正式舊版者在新版待確認期間仍可使用舊版 |
| I9-019 | staging 與 production 共用小型主機造成記憶體競爭 | P0 | MITIGATED | 首租戶驗證期間停止 staging compute；後續將 staging 移機或建立明確啟停／資源政策 |
| I9-020 | 正式 Gemini 專案遭 403，內部整理、掃描理解與雲端 OCR 不可用 | P0 | VERIFIED | 所有必要 Provider 必須以真實呼叫通過；失效路徑切換至已驗證 Provider 並保留本機後備 |
| I9-021 | 高量保護只統計預設 `celery` queue，未統計獨立 Input queues | P0 | VERIFIED | admission guard 同時統計 `celery`、`input.document`、`input.media`，任一來源造成的總積壓都受上限保護 |
| I9-022 | 從「所有資產」刪除來源時，對應 Document 投影可能仍可被檢索 | P0 | VERIFIED | 刪除來源必須先走共用 deny-first 文件撤權，清除檢索、快取、Wiki 與圖譜投影；撤權失敗時不可只隱藏來源 |
| I9-023 | 同租戶同時上傳多種來源時，tenant admission lock upgrade 可能造成 PostgreSQL deadlock 與 HTTP 500 | P0 | FIXED_IN_CODE | admission 使用不與 FK KEY SHARE 衝突的序列化鎖；雙交易測試及正式四格式並行上傳均不得失敗 |
| I9-024 | `.env.production` 三個非機密設定帶行尾註解，獨立 Docker 維運工具解析失敗 | P1 | VERIFIED | 設定值與註解分離；Compose 及獨立容器均能載入型別正確的設定 |

### 實作進度（持續追加）

- 2026-09-03 I9-1 `FIXED_IN_CODE`：常見 PCM／錄音格式、錯誤分類與有界重試完成；Code Review PASS。
- 2026-09-03 I9-2 `FIXED_IN_CODE`：媒體 Worker 隔離、資源限制、stale job reconciliation 與安全重送完成；Code Review PASS。
- 2026-09-03 I9-3 `FIXED_IN_CODE`：serving-mode-aware answer-ready、互斥狀態、來源層級首頁統計與殘留覆核項目排除完成；Code Review PASS。
- 2026-09-03 I9-4 `FIXED_IN_CODE`：核心狀態用詞、可操作狀態卡、deep link、白話錯誤、自動重試說明與追蹤碼完成；Code Review PASS。
- 2026-09-03 I9-5 `FIXED_IN_CODE`：人工確認依來源分組、來源／候選雙重計數、風險摘要及 rolling compatibility 完成；Code Review PASS。
- 2026-09-03 I9-6 `FIXED_IN_CODE`：真實 `pcm_s24le` WAV 正規化回歸、76 項後端 focused tests、135 項前端 tests 與 production build 完成；Code Review CONDITIONAL PASS，正式 PostgreSQL／容器驗證移入 I9-7。
- 2026-09-03 I9-7 `DEPLOYED / VERIFYING`：正式環境備份、migration、獨立 Input Worker 與 release `243d784` 已上線；兩支 24-bit PCM WAV 均成功轉寫並進入人工確認，孤兒圖片成功復原且可問答，5 支影片維持人工確認，原始來源未被覆寫。
- 2026-09-03 I9-7 擴大檢查：真實 Ask 測試發現第一方網頁 `source_system=web` 被 Connector ACL 誤擋，且既有完成文件缺 lexical projection；八策 4 個既有 chunks 已安全回填。永久修復、Redis 認證修復與回歸測試完成，待第二版部署後再驗證引用鏈。
- 2026-09-03 I9-8 `DEPLOYED / VERIFYING`：release `1a371e4` 上線；7 條正式 Provider 真實呼叫全數通過，三條 queue 的總量保護已由正式 runtime 驗證。第一輪來源已清空，等待李永仁第二輪高量真實複測。
- 2026-09-03 I9-9 `DEPLOYED / VERIFIED`：release `b79d0ca` 上線；統一資產刪除已固定先撤銷相容 Document 與所有問答投影，失敗時 fail-closed。正式 runtime 載入新邏輯，八策可見來源與文件均維持 0。
- 2026-09-03 I9-10 `FIXED_IN_CODE`：正式四格式同時上傳重現 tenant row lock upgrade deadlock；改用 `FOR NO KEY UPDATE`，隔離 PostgreSQL 28 項回歸與雙交易 deadlock 測試通過，待 Code Review 後部署再跑正式四格式 Gate。

## 4. 實作階段與 Code Review Gate

### I9-1：媒體正規化與錯誤分類

- 擴充常見 PCM 與錄音裝置格式矩陣。
- 原始檔不變，內部處理使用標準化代理。
- 建立 permanent、transient、resource、provider failure taxonomy。
- 永久錯誤立即停止；可恢復錯誤才退避重試。
- 完成後建立獨立 Code Review 紀錄，通過才進 I9-2。

### I9-2：資源隔離與孤兒工作復原

- 文件、音訊、影片分流到獨立 queue 或受控執行邊界。
- 限制媒體並行度、執行緒及暫存空間。
- 增加 heartbeat／lease／stale-job reconciliation。
- WorkerLost 不得永久呈現處理中。

### I9-3：單一狀態真相與 answer-ready

- 定義並實作唯一狀態投影。
- `可問答` 必須由已發布且可檢索的知識決定，不能由 `active` 推測。
- 終態轉換清除目前錯誤，但保留事件歷史。
- 建立跨表一致性測試與修復工具。

### I9-4：Input 首頁與失敗處理 UX

- 統一「系統處理中／等待人工確認／已可問答／需要處理」。
- 狀態卡可點擊並提供明確 CTA。
- 顯示使用者可理解的原因、是否會自動重試、下一步與追蹤碼。
- 手機版不得依賴 hover 或寬螢幕資訊。

### I9-5：來源層級人工確認

- 預設依來源分組，顯示候選數、風險與阻擋原因。
- 細節片段按需展開；支援受政策控制的批次核准／退回。
- 兩人小型租戶的職責分離流程必須可完成且可理解。

### I9-6：生產可靠性驗證

- 建立代表性格式 corpus：手機、DJI／錄音筆、會議工具、常見 Office、圖片及影片。
- 執行格式矩陣、故障注入、WorkerLost、provider timeout、重送與恢復測試。
- 完成桌機及 iPhone Safari 主要旅程。
- 驗證問答能命中已發布內容並回到原始證據。

### I9-7：正式部署、既有資料修復與租戶複測

- 部署前備份並記錄回滾點。
- 修復八策既有兩支音檔、卡住圖片、錯誤統計及可安全重建的衍生狀態。
- 不覆寫原始來源，不替使用者做內容核准。
- 交付李永仁與陳宥竹的複測清單。

## 5. 狀態詞彙契約

| 產品文字 | 意義 | 責任人 | 下一步 |
|---|---|---|---|
| 已收到 | 原始來源已安全保存 | 系統 | 等待排程 |
| 系統處理中 | 系統正在解析、OCR、轉錄或建立索引 | 系統 | 可離開頁面，稍後查看進度 |
| 等待人工確認 | 系統已產生候選，但尚未成為正式可問答知識 | 租戶授權審核者 | 核准、修正或退回 |
| 已可問答 | 已發布且檢索 gate 通過 | 使用者 | 直接進入「問知識」 |
| 需要處理 | 系統不能自行完成 | 使用者或管理員 | 依白話原因採取指定動作 |

## 6. 持續新增問題格式

每個新問題追加以下資料，不改寫歷史：

```text
ID：I9-xxx
首次發現時間／租戶：
使用者症狀：
影響範圍：
根因：
暫時處置：
永久修復：
資料修復：
測試證據：
Code Review：
部署版本：
租戶複測：
狀態：OPEN / FIXED_IN_CODE / DEPLOYED / VERIFIED / CLOSED
```

## 7. 宣稱邊界

I9 完成前，不宣稱所有音檔、影片或圖片均已達到生產可靠。I9 程式部署後，也只能宣稱「已進入首租戶複測」；必須待八策代表性來源成功完成 Input → 人工確認 → 發布 → Ask 引用，才可將本輪問題關閉。

## 8. 2026-09-03 正式部署與系統驗證

- 生產 release：`8ea5bb1`。
- 部署前 PostgreSQL 備份：`/opt/enclave/backups/enclave_pre_input_i9_20260903_1525_input_i9.dump`。
- 備份 SHA-256：`6f9c7cec9f838ec212da31d59b147592ca4ede803c3a20cea40e81adb7c0d467`；已用 `pg_restore --list` 驗證可讀。
- API、前端、Gateway、core worker、Input worker 全部 healthy；正式網域 `/health` 回傳 database ready。
- Input worker 獨立使用 `input.media,input.document` queue、concurrency 1 與 2 GiB 上限；主機驗證時 available memory 約 4.5 GiB。
- 兩支原失敗 WAV 均成功完成，分別產生 16 與 5 筆候選；狀態為「等待人工確認」。
- 原卡住 JPEG 經 stale reconciliation 自動重新排程並完成；因為是首版且仍待人工確認，不再提前列為可問答。
- 八策目前 9 個來源：已可問答 1、等待人工確認 8、系統處理中 0、需要處理 0。
- 人工確認工作區：8 個來源、179 筆候選，預設先依來源分組。
- 正式 Ask 驗證問題「請根據目前公司知識，簡要說明曠職相關規定，並提供來源。」成功產生 557 字回答及 3 筆引用；引用均可回到已匯入網頁文件。驗證 request ID：`2cf456ca-5c84-4bd0-b0d8-0fe2bfe61bde`。
- 本次沒有代替租戶核准任何音訊、圖片或影片候選。
- staging 的 DB／Redis 保留，但 compute services 暫停，以避免與首租戶 production 爭用記憶體；恢復前需先完成容量決策。

## 9. 李永仁第一輪複測清單（歷史）

本節保留第一輪修復的驗證內容。2026-09-03 已依同意清空第一輪來源，以下 9 筆來源的預期數字不再適用；第二輪請改依第 11 節執行。

請先用李永仁本人已設定的密碼重新登入，再依序驗證：

1. 首頁應顯示：全部來源 9、已可問答 1、系統處理中 0、等待人工確認 8、需要處理 0。
2. 點「已可問答」應直接進入「問知識」，不再只顯示一個不知道如何使用的數字。
3. 提問「請根據目前公司知識，簡要說明曠職相關規定，並提供來源。」回答下方應出現可點擊的網頁來源。
4. 點「等待人工確認」應看到 8 個來源分組，而不是把 179 個候選誤認成 179 份文件。
5. 兩支 WAV `DJI_34_20260331_115344.WAV` 與 `DJI_15_20260309_134103-職場性騷擾音檔.WAV` 應顯示等待人工確認，不得再顯示失敗或重新處理。
6. `IMG_8592.jpeg` 應顯示等待人工確認，不得再永久停在系統處理中，也不得在首版尚未確認前列入已可問答。
7. 再上傳一支代表性的短音檔，確認可依序經過「系統處理中 → 等待人工確認」，過程可離開頁面再回來，不必靠重新整理才能救回工作。
8. 若高風險候選由建立者本人開啟，系統應明確說明不能自行核准；請由另一位 Owner 完成人工確認。

李永仁回報上述結果後，將「租戶複測」補入本文件；全部通過才把相關問題由 `VERIFIED` 關閉為 `CLOSED`。

## 10. 第二輪高量真實測試前檢查（2026-09-03）

第二輪預期會比第一次上傳更多來源，因此本輪不只檢查既有個案，也檢查容量、外部服務、分段上傳、排程、復原與資源保護。

### 10.1 已確認基線

- 八策租戶方案為 `enterprise`；目前 2 位啟用使用者，上限 10 位。
- 文件數、儲存量、月問答、月 Token 與月成本沒有租戶硬上限；目前計量儲存約 395.99 MiB。
- 分段續傳已啟用：預設每段 8 MiB、允許 5–16 MiB、工作保留 24 小時；已提交的 8 個上傳 session 沒有殘留未完成 session。
- 文件／圖片單檔上限 50 MiB；音檔單檔上限 50 MiB、最長 4 小時；影片單檔上限 500 MiB、最長 60 分鐘。
- 新增知識介面支援多檔排隊、前置格式與容量檢查、逐檔進度、失敗單筆重試、暫停與缺塊續傳；未完成草稿保存在該瀏覽器。
- 正式三個 queue 均為 0；core worker 與獨立 Input worker 沒有 active、reserved 或 scheduled 工作。
- API、前端、Gateway、Worker、PostgreSQL、Redis 與向量服務均 healthy；部署後重啟次數為 0，沒有 OOMKilled 或新 Traceback。
- 主機約 7.8 GiB RAM，檢查時 available 約 4.5 GiB；Input worker 維持 concurrency 1、prefetch 1 與 2 GiB 容器上限，以可靠排隊取代同時大量吃記憶體。
- 清理 7 天前 Docker build cache 後釋放 14.76 GB；正式磁碟可用空間約 57 GB。
- 第二輪前 PostgreSQL 備份：`/opt/enclave/backups/enclave_pre_second_tenant_test_20260903_075923.dump`。
- 備份 SHA-256：`72ac1dad4b5dca2c21d545bf9d6fc23cdffd1733d7251f1b73331d744935cb03`；已用 `pg_restore --list` 驗證可讀。

### 10.2 擴大檢查發現與處理

- 初次真實 Provider probe 共 7 條能力：OpenAI 問答、Ollama 向量索引、OpenAI 一般語音、OpenAI 長音檔通過；Gemini 內部整理、掃描理解與 Cloud OCR 因供應商專案 403 未通過，不能只以「API Key 有設定」視為可用。
- 已將三條失效路徑切換到既有且已實測可用的 OpenAI 憑證，Cloud OCR 同時保留本機 OCR 基礎。部署後重新執行 7 條正式真實呼叫，結果為 7/7 通過：主要問答、內部整理、掃描理解、向量索引、一般語音、長音檔與 Cloud OCR 均可連通及運作。
- queue guard 原本只讀取 `celery`，未看獨立的 `input.document` 與 `input.media`；永久修復已統計三條 queue 總深度，並在飽和回應中保留各 queue 深度。正式 runtime 回傳三條 queue 均為 0，總上限 500。
- release `1a371e4` 已部署；API、前端、Gateway、Worker、Input Worker 與 Beat 均 healthy，restart 0、OOMKilled false，近期沒有新 Traceback、Critical、WorkerLost 或 OOM。
- 本機 focused tests 共 11 項通過；`ruff` 與 `git diff --check` 通過。正式網域 `/health` 及部署後 Provider／queue／容器檢查均通過。

### 10.3 第二輪測試的正常預期

- 多個檔案會依序上傳；處理工作會可靠排隊，不代表每一份音檔或影片同時完成。
- 頁面可離開；已收到的來源在背景處理。回到「所有資產」可看來源層級進度。
- 網路中斷時可重試；已確認的分塊不需重傳。若超過 24 小時才回來，該上傳工作可能過期，需重新選檔。
- 影片與長音檔比文件慢屬正常；「系統處理中」才是系統責任，「等待人工確認」則是 Owner／授權審核者的下一步。
- 若來源超過單檔大小或影片長度上限，介面應在送出前直接說明限制，不應讓工作無限處理後才失敗。

本節在部署與正式 probe 完成後更新 release、驗證結果與李永仁第二輪複測結果；尚未取得真實複測前，不宣稱 I9 已關閉。

### 10.4 李永仁第一輪資料清空與第二輪基線

- 清空前唯讀盤點：9 個可見來源均由李永仁建立；包含影片 5、音檔 2、圖片 1、網頁 1，另有 9 個 revision、230 個衍生 artifact、9 個 ingestion job 及 8 個已提交 upload session。
- 清空前已建立可回復的 PostgreSQL 備份：`/opt/enclave/backups/enclave_pre_second_tenant_test_20260903_075923.dump`；SHA-256 與還原清單驗證均通過。
- 兩個具相容 Document 投影的來源先走 deny-first 文件撤權，再將其餘來源 tombstone；沒有硬刪原始二進位，必要時仍可由備份或保留資料復原。
- 清空後正式 API 顯示可見來源 0、等待人工確認 0；資料庫顯示可見 Document 0、可見 SourceAsset 0，9 個舊來源及 2 個舊 Document 均已 tombstone。
- 重新詢問第一輪曠職問題後，回答引用來源為 0；驗證用對話已移除，證明舊知識不再由 Ask 檢索。
- 八策租戶、陳宥竹與李永仁帳號及兩人的 Owner 權限均保留；此次依約只清空來源，沒有刪除使用者原有對話紀錄。
- 清理過程發現 I9-022：統一資產庫的來源刪除原先未保證同步撤銷相容 Document 投影。永久修正改為刪除前呼叫共用撤權服務；若撤權失敗回傳 409，避免出現「介面看不到但 AI 仍可能查到」的半完成狀態。
- 永久修正已部署為 release `b79d0ca`。部署後 6 個應用容器均正常、restart 0、OOMKilled false；7/7 Provider probe 再次通過，三條 queue 深度均為 0，正式資料庫再次確認可見來源 0、可見文件 0、啟用使用者 2、Owner 2。

## 11. 李永仁第二輪高量真實複測

第二輪起點已歸零。登入後應先看到全部來源、已可問答、系統處理中、等待人工確認與需要處理均為 0。

建議依下列順序測試，讓單一格式問題不會掩蓋整批結果：

1. 先上傳各 1 份短文件、圖片及短音檔，確認都能從「已收到／系統處理中」前進，不需按重新整理救援。
2. 第一組開始處理後，可再用多檔上傳加入 5～10 份混合文件與圖片；系統可排隊，不要求同時完成。
3. 再加入 1 份較長音檔與 1 支影片，檢查離開頁面再回來仍可追蹤進度。
4. 對完成解析的來源進行人工確認；高風險項目由另一位 Owner 確認，建立者不可自行核准時應看到清楚說明。
5. 發布後到「問知識」提出只能由本批資料回答的問題，回答必須附來源；點開來源應能回到正確檔案、時間碼或證據內容。
6. 刪除一個本輪測試來源後，再問只存在於該來源的問題；系統不得再引用已刪除來源。

正常現象：大量來源會可靠排隊；影片與長音檔比文件慢；「等待人工確認」代表系統已完成候選產生、下一步由 Owner 處理。異常現象：工作長時間沒有狀態變化、同一檔案重複建立來源、需要靠重新整理才推進、失敗訊息沒有原因／下一步／追蹤碼、已刪除來源仍出現在引用。

若發生異常，請保留發生時間、檔名、檔案類型與畫面上的追蹤碼並回報；不需要重複上傳同一檔案多次。修復紀錄將繼續追加在本文件，不改寫已發生的歷史。

## 12. 最終驗收擴大診斷（2026-09-03）

- 正式端到端第一輪：同時建立短文字、圖片、24-bit PCM WAV 與含語音短影片；四筆均成功由 queued 前進，文字成為已可問答，圖片／音檔／影片成為等待人工確認。問答正確回答唯一碼 8246 並產生 2 筆來源引用；刪除後再次提問引用為 0，最後來源與人工確認均回到 0。
- 正式端到端第二輪重跑時，三筆建立成功、文字來源偶發 HTTP 500。request `76d55ce4` 的正式日誌確認為 `ensure_job()` 對 tenant row 執行 `FOR UPDATE` 時發生 `DeadlockDetected`，不是檔案格式或 Provider 失敗。
- 根因：並行交易已因新增 tenant-FK 資產列持有 `KEY SHARE`，再一起升級成 `FOR UPDATE` 會互相等待。永久修正為 `FOR NO KEY UPDATE`：仍會序列化同租戶 admission，但允許既有 FK KEY SHARE，不再進行衝突式 lock upgrade。
- 新增 PostgreSQL 雙交易測試：兩個交易先各自建立 asset／revision、同步抵達 admission，再各自建立 ingestion job 並 commit；兩筆都必須成功。
- candidate 在獨立暫時 PostgreSQL 資料庫完成 28 項測試：ingestion orchestrator 9、I7 admission／fairness／recovery 8、P0 correctness 10、data lifecycle 1，全數通過。暫時資料庫於測試後自動刪除，正式八策資料未被測試使用。
- 正式設定衛生檢查另發現 `ACCESS_TOKEN_EXPIRE_MINUTES`、`VOICE_STT_ENABLED`、`MAX_FILE_SIZE` 帶行尾註解，會被部分非 Compose 工具視為值的一部分。已備份並改成純值；獨立容器驗證為 `480 / 52428800 / True`。

本節尚未完成條件：I9-023 部署、正式四格式並行 Gate 重跑、來源層級人工確認分組、刪除後 0 引用、瀏覽器手機版主要畫面與最終乾淨基線全部通過。
