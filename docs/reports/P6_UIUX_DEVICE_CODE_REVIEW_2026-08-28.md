# P6 UI/UX、無障礙與裝置驗證 Code Review — 2026-08-28

狀態：`INTERNAL SOFTWARE GATE PASS / PHYSICAL DEVICE LAB DEFERRED`

本輪完成 UI/UX 體質、無障礙、persona route contract、異常狀態、證據深連結、
responsive media intake、視覺回歸與效能預算的實作及 Code Review。未發現尚未處理的
Critical／High correctness、authorization 或 accessibility finding。

## 完成項目

- 核心公開頁與 authenticated routes 加入 axe WCAG 2.0／2.1／2.2 A／AA 自動檢查。
- 新增 skip link、唯一 main landmark、mobile drawer dialog、focus trap、Escape focus
  restoration、reduced-motion 與 44px 觸控目標。
- 六種 Demo persona 逐一以 server bootstrap 的 capability／navigation 為權威，驗證
  capability-guarded deep link；viewer 對 superuser API 仍為 403。
- 統一 empty／loading／partial／failed／retry 狀態，新增 offline、timeout、quota、
  provider-disabled 與 request trace 訊息。
- 長時間 knowledge processing task 寫入受限 local recovery index，重新整理或切頁後
  可回到資產進度；ready／failed 後自動移除。
- 文件頁碼／段落、圖片區域、音訊時間範圍、影片時間點／frame 皆有可見 locator；
  Review Queue 只接受 allowlist 站內 evidence route，無效連結會 fail closed 並禁止核准。
- 修正 MKA knowledge card 原先指向不存在的 `/knowledge/knowhow/...`，統一為實際
  `/knowhow/...` 模組路由。
- 建立 desktop、Pixel 7、iPhone 15 viewport／UA 與 Galaxy Tab S9 的 responsive matrix；
  驗證拍照、錄音、錄影 capture entry、多檔 queue、離線、慢速 API 與恢復提示。
- 建立 landing、login、mobile knowledge intake 的跨平台 snapshot 路徑，以及 navigation、
  total transfer 與 largest JS browser budget。

## Code Review 關閉 findings

| Finding | 修正 |
|---|---|
| 進場文字以 opacity 動畫造成短暫 contrast violation | 動畫只保留位移；reduced-motion 完全關閉動畫 |
| Review Queue 內層使用第二個 main landmark | 改為 section，整個 workspace 僅保留 Layout main |
| 關閉的 mobile drawer 仍留在 accessibility tree | 僅開啟時 mount，宣告 modal dialog 並鎖定焦點／body scroll |
| Account disclosure 使用不完整 ARIA menu pattern | 回復一般 disclosure controls，保留 Escape 與 focus restoration |
| Evidence deep link 可直接使用任意字串 | route／query／locator allowlist；外部或未知 link fail closed |
| MKA evidence link 指向不存在路由 | 後端 publisher 與 review provider 改為 `/knowhow/:id` |
| 視覺基線抓到 lazy loader 而非完成畫面 | screenshot 前等待頁面語意 heading，並使用平台中立 snapshot path |
| Service worker 可能讓 browser test 使用舊 shell | acceptance context 阻擋 service worker，確保檢查目前 build |

## 驗證結果

- P6 Playwright：29 passed。
  - Chromium desktop：accessibility、keyboard、六 persona route、四種 evidence、visual、performance。
  - Pixel 7／iPhone 15 emulation／Galaxy Tab S9：responsive、capture entry、offline、slow API、recovery、axe。
- Frontend Vitest：31 files／108 tests passed。
- Backend P6-related regression：39 passed。
- ESLint、TypeScript、Vite production build、Ruff、`git diff --check`：PASS。
- 核心 accessibility：0 Critical／Serious violation。

## 明確邊界

本輪的 Android／iPhone／tablet 是可重複的瀏覽器 device emulation；desktop 另以實際
in-app browser 檢視。自動測試驗證 capture input、queue、interruption recovery 與網路
降級 UI，但不宣稱已完成真機相機／麥克風權限、數小時實體上傳、真實工廠噪音 ASR
品質或 Mobile Safari 原生 media stack。這些仍列為 Commercial GA 外部／實體裝置
campaign，不得由本報告推論為 PASS。

上述邊界不影響 P7 內部租戶營運與商業沙盒開發；P6 的內部 software gate 完成。
