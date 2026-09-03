# Input I9 第二輪租戶測試前最終驗收

- 日期：2026-09-03
- 租戶：八策股份有限公司
- 正式環境：`https://kachu.tw`
- 正式 release：`dd5a6bd`

## 1. 結論

李永仁第一輪回報的四項問題已完成根因修復、正式部署及端到端驗證；擴大診斷另外找出的並行上傳 deadlock、刪除後檢索殘留風險、獨立 queue 漏算、正式環境設定格式、release 無法識別及舊環境檔覆蓋 canonical 設定等問題也已一併修正。

目前正式環境已回到第二輪測試的乾淨起點，帳號與 Owner 權限保留。技術驗收通過，可以開始第二輪較高量的真實資料測試。第二輪仍是必要的租戶驗收：它用八策實際設備、網路與內容驗證代表性樣本，不能由合成測試取代。

## 2. 第一輪四項問題與結果

| 第一輪問題 | 根因／產品問題 | 修復後行為 | 驗證 |
|---|---|---|---|
| 音檔上傳兩次均失敗，重新整理無效 | 24-bit PCM WAV 解碼與媒體 worker 復原不足；重新整理不能修復後端工作 | 支援真正 PCM 24-bit WAV；工作具 lease、heartbeat、stale reconciliation 與明確重試 | 正式 24-bit PCM WAV 上傳、轉錄並進入等待人工確認 |
| 不知道「待覆核」是否代表系統仍在跑 | 系統狀態與人員責任混用 | 統一為「系統處理中」與「等待人工確認」兩個互斥責任狀態 | 正式首頁、資產庫與手機頁面均使用新詞彙 |
| 不知道「待審核」是人或系統 | 同一概念多個名稱，且未說明下一步 | 統一為「等待人工確認」，清楚表示下一步由 Owner／授權審核者處理 | 人工確認頁以來源分組顯示，正式 Gate 為 3 個來源、16 筆候選 |
| 「可使用 2」不知道怎麼用 | 指標名稱沒有描述能力，也沒有直接工作入口 | 改為「已可問答」，整張卡可直接進入「問知識」 | iPhone 尺寸正式網域實際點擊成功進入 Ask，輸入框可用 |

## 3. 擴大診斷與周邊強化

### 3.1 並行上傳

四格式並行重跑曾發現一次文件 HTTP 500。正式日誌定位為 tenant admission 的 PostgreSQL row-lock upgrade deadlock。修正採用 `FOR NO KEY UPDATE`，保留同租戶 admission 序列化與容量限制，同時避免與外鍵 `KEY SHARE` 形成循環等待。

修正後正式同時上傳短文字、圖片、24-bit PCM WAV 與含語音短影片，四筆全部 HTTP 202，沒有 deadlock 或 failed。

### 3.2 刪除、撤權與檢索一致性

來源刪除現在會先撤銷相容 Document 投影；撤權失敗時拒絕回報刪除成功，避免「介面看不到、AI 仍查得到」。正式 Gate 中，刪除前 Ask 有 2 筆來源，刪除全部測試來源後相同問題為 0 筆來源。

### 3.3 排程、容量與復原

- 文件與媒體使用受控 queue；Input worker 限制並行度與容器資源，採可靠排隊。
- queue guard 同時計算 `celery`、`input.document`、`input.media`，不再漏看獨立 Input queue。
- 工作具 heartbeat、lease、stale-job reconciliation；WorkerLost 或瀏覽器離開不應永久停在處理中。
- 未完成分段上傳可在有效期內續傳，已確認區塊不需重傳。

### 3.4 外部 API 與正式環境

正式環境七條真實能力 probe 全部通過：主要問答、內部整理、掃描理解、向量索引、一般語音、長音檔與 Cloud OCR。正式環境檔的三個行尾註解已改為純值，確保 Compose 與獨立維運工具使用相同設定語意。

最後重啟測試曾抓到 release 目錄舊環境檔會讓三條能力退回已失效 Gemini。現在 release 的 production、DB admin 與 maintenance env 都指向 `/opt/enclave` 唯一 canonical 檔案，檔案權限為 0600；舊副本保存在權限 0700 的備份目錄。修正後重新執行真實 Provider probe 為 7/7 通過。

公開 `/health` 與前端 `/release.json` 現在都能辨識本次 release：`input-i9-dd5a6bd`、完整 source commit、schema head、route contract hash 與 deployment manifest 一致，後端 `identifiable=true`。未接正式流量的空白 Compose 測試專案及其新建容器、network、volume 已全部移除，正式資料未受影響。

### 3.5 手機 UX

以 390×844 iPhone 尺寸在正式網域驗證首頁、所有資產、等待人工確認、新增知識與問知識。頁面沒有 body 橫向溢位，狀態卡可操作，空狀態與責任文字可理解；前端相關 4 個測試檔、11 項測試全部通過。

## 4. 自動化與正式端到端證據

- 後端本機 focused tests：10 passed。
- 隔離 PostgreSQL candidate gate：28 passed。
- 前端關鍵頁面：11 passed。
- 外部／本機 Provider：7/7 passed。
- 正式四格式並行上傳：4/4 HTTP 202，狀態轉換全部符合預期。
- 正式人工確認：3 個來源分組、16 筆候選。
- 正式 Ask：刪除前正確回答唯一碼 8246、2 筆引用；刪除後 0 筆引用。
- 正式容器：restart 0、OOMKilled false；三條 queue 為 0；近期日誌無 deadlock、Traceback、Critical、WorkerLost、OOM。
- Release identity：後端 `identifiable=true`，前後端 metadata 一致。

## 5. 第二輪乾淨基線

- 可見 SourceAsset：0。
- 可見 Document：0。
- 未完成 upload session：0。
- 啟用使用者：2。
- Owner：2。
- 人工確認來源與候選：0。
- 隔離測試資料庫：0。

第一輪來源使用 tombstone／撤權處理，原始來源沒有被不必要地硬刪；部署前備份仍保留可回復。正式合成 Gate 只刪除本次精確記錄 ID 的測試來源，沒有碰觸其他租戶資料。

## 6. 李永仁第二輪驗收重點

1. 先各上傳一份文件、圖片與短音檔，再加入 5～10 份混合來源。
2. 再上傳一份較長音檔與一支影片；可離開頁面，稍後回來看狀態。
3. 確認來源只會處於「系統處理中」「等待人工確認」「已可問答」或「需要處理」等可理解狀態。
4. 由適當 Owner 完成人工確認；高風險候選不得由建立者自行核准。
5. 發布後提問只能由本批資料回答的問題，答案必須附正確來源、時間碼或證據。
6. 刪除其中一份來源後再問同一問題，不得再引用已刪除來源。

若異常，請保留發生時間、檔名、格式、檔案大小與畫面追蹤碼；不需反覆上傳同一檔案。新問題會持續追加到 `INPUT_I9_FIRST_TENANT_PRODUCTION_HARDENING.md`，保留症狀、根因、修復、測試、部署與租戶複測歷史。

## 7. 宣稱邊界

本次結論是「已完成程式、正式環境與合成代表性 corpus 的技術驗收，可開始第二輪真實測試」，不是宣稱所有未知編碼、損壞檔案或外部供應商事件永遠不會失敗。系統目前具備可診斷狀態、重試／復原、追蹤碼與 fail-closed 行為；第二輪真實內容完成 Input → 人工確認 → 發布 → Ask 引用後，才將本輪標記為 `CLOSED`。
