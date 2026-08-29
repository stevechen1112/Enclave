# Input I3 裝置與中斷驗證矩陣

日期：2026-08-29
工作區基準：Git `d85b150` 加未提交的 Input I0–I3 變更
Node.js：22.18.0
Playwright：1.58.2

## 自動化證據

| 環境／情境 | 結果 | 證據邊界 |
|---|---:|---|
| Desktop Chrome（Playwright Chromium） | PASS | capture create → chunk checksum upload → complete → canonical asset |
| Pixel 7 viewport／touch Chromium emulation | PASS | 行動版面與相同 capture-to-asset 流程；不是 Android 實機 |
| iPhone 15 viewport／touch Chromium emulation | PASS | iPhone 尺寸與觸控流程；**不是 Mobile Safari** |
| Galaxy Tab S9 Chromium emulation | PASS | 平板版面與相同流程 |
| 麥克風 permission denied | PASS | component test 確認不建立 session，顯示可執行錯誤 |
| page hidden／切 App 事件 | PASS | component test 會 `requestData()` 優先封存目前片段並顯示風險提示 |
| 網路中斷／重新登入 | PASS（軟體層） | IndexedDB chunk queue 與 I2 acknowledged-part resume；真實網路切換仍待實機 |
| 模擬媒體樣本 | PASS | bytes `factory-audio`，SHA-256 `5a051deaa734b4f5e9b1e350abe80bd8a5a1c691379b916544c80cb724d49eb1` |

## 尚待實體裝置認證

下列項目不能由桌面 Chromium 模擬取代，因此目前不得標記為 PASS：

| 裝置／情境 | 狀態 | 必須保存的證據 |
|---|---:|---|
| iPhone 實機 Mobile Safari | PENDING | iOS／Safari 版本、裝置型號、錄音 MIME、樣本 SHA-256、session id、asset id |
| Android 實機 Chrome | PENDING | Android／Chrome 版本、裝置型號、錄音 MIME、樣本 SHA-256、session id、asset id |
| 鎖屏 30 秒後返回 | PENDING | 中斷時間、最後安全 offset、缺塊數、復原結果、樣本 hash |
| 切換其他 App 30 秒後返回 | PENDING | visibility event、最後安全 offset、復原結果、樣本 hash |
| 來電／系統音訊中斷 | PENDING | OS event、MediaRecorder state、復原／重啟行為、是否遺失片段 |
| Wi-Fi ↔ 4G／5G 切換 | PENDING | chunk 重送次數、重複抑制、完成 hash、總復原時間 |
| 裝置空間不足 | PENDING | browser quota、失敗 chunk、使用者提示與已保存片段 |

## 實機執行規則

每次測試使用新的 capture session，錄製至少 3 分鐘並跨過六個 30 秒 chunk。報告必須記錄裝置、OS、瀏覽器完整版本、網路、開始／中斷／恢復時間、session id、asset id、每段 SHA-256 與最終狀態；不得只附螢幕截圖或寫「可用」。

這份矩陣證明內部軟體 gate 已完成，但實體 iPhone Safari／Android Chrome 與系統中斷認證仍待執行。
