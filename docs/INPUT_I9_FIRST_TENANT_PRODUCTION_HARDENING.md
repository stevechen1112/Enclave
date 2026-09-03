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

### 實作進度（持續追加）

- 2026-09-03 I9-1 `FIXED_IN_CODE`：常見 PCM／錄音格式、錯誤分類與有界重試完成；Code Review PASS。
- 2026-09-03 I9-2 `FIXED_IN_CODE`：媒體 Worker 隔離、資源限制、stale job reconciliation 與安全重送完成；Code Review PASS。
- 2026-09-03 I9-3 `FIXED_IN_CODE`：serving-mode-aware answer-ready、互斥狀態、來源層級首頁統計與殘留覆核項目排除完成；Code Review PASS。
- 2026-09-03 I9-4 `FIXED_IN_CODE`：核心狀態用詞、可操作狀態卡、deep link、白話錯誤、自動重試說明與追蹤碼完成；Code Review PASS。
- 2026-09-03 I9-5 `FIXED_IN_CODE`：人工確認依來源分組、來源／候選雙重計數、風險摘要及 rolling compatibility 完成；Code Review PASS。
- 2026-09-03 I9-6 `FIXED_IN_CODE`：真實 `pcm_s24le` WAV 正規化回歸、76 項後端 focused tests、135 項前端 tests 與 production build 完成；Code Review CONDITIONAL PASS，正式 PostgreSQL／容器驗證移入 I9-7。
- 2026-09-03 I9-7 `DEPLOYED / VERIFYING`：正式環境備份、migration、獨立 Input Worker 與 release `243d784` 已上線；兩支 24-bit PCM WAV 均成功轉寫並進入人工確認，孤兒圖片成功復原且可問答，5 支影片維持人工確認，原始來源未被覆寫。
- 2026-09-03 I9-7 擴大檢查：真實 Ask 測試發現第一方網頁 `source_system=web` 被 Connector ACL 誤擋，且既有完成文件缺 lexical projection；八策 4 個既有 chunks 已安全回填。永久修復、Redis 認證修復與回歸測試完成，待第二版部署後再驗證引用鏈。

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

## 9. 李永仁複測清單

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
