# Input I9-6 Code Review：可靠性驗證

日期：2026-09-03

結論：CONDITIONAL PASS，可進入 I9-7 正式環境驗證

## 新增真實格式回歸

- 使用本機 FFmpeg 8.1.1 產生真正的 24-bit PCM WAV，不使用假 probe payload。
- 完整驗證 `ffprobe -> codec policy -> MP3 瀏覽代理 -> 10 秒安全分段`。
- 這是八策 DJI／錄音裝置 `pcm_s24le` 失敗根因的直接 regression test。

## 驗證結果

- Input／media／orchestrator／worker recovery／readiness／review／video focused suite：76 passed。
- Input I2、I4、I5 及部分 I3／I6／I8／I9 broader suite：49 passed；其餘 10 項因本機 PostgreSQL `localhost:5435` 未啟動而無法執行，不是 assertion regression。
- 前端完整 Vitest：40 files、135 tests 全部通過。
- TypeScript `tsc -b`：通過。
- Vite production build：通過，3257 modules transformed。
- Python `compileall`：通過。
- Compose YAML 結構已於 I9-2 以 parser 驗證；完整 interpolation 需使用 production `.env.production`，本機刻意沒有正式機密檔。

## Code Review 發現與修正

1. 前端完整測試發現 LifecycleBadge 的兩個舊文案 assertion 仍期待「可搜尋／尚不可查」；已更新為產品契約「已可問答／尚不可問答」。
2. 真實 PCM 測試先建立獨立 chunks 目錄，與 worker 的實際暫存目錄契約一致。
3. 仍禁止以 mock codec matrix 取代真實媒體測試；兩者都保留，分別涵蓋 policy 與 executable integration。

## 進入 I9-7 的必要條件

- 正式環境 compose interpolation 與容器 health 通過。
- 部署前資料庫備份與 release rollback 點完成。
- 正式 Worker 確認分流至 `input.media,input.document` 且 concurrency 1。
- 既有兩支 WAV 重新處理；卡住圖片由 stale reconciliation 復原。
- API 驗證來源／候選雙重計數、answer-ready 與錯誤追蹤碼。
- 不代替租戶核准高風險候選。
