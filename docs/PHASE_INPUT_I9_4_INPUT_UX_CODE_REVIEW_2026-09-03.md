# Input I9-4 Code Review：Input 狀態與修復 UX

日期：2026-09-03

結論：PASS，可進入 I9-5

## 變更範圍

- 核心知識導覽統一使用「人工確認」，不再混用待覆核／待審核。
- 首頁每個狀態卡都有下一步；「已可問答」直接進入問知識。
- 資產庫支援首頁 query-string deep link，進頁後會真的套用對應狀態篩選。
- 資產詳情新增四種白話行動說明：背景處理、人工確認、已可問答、需要處理。
- 錯誤優先顯示後端安全的 `user_message`，說明是否還會自動重試，並顯示 correlation 追蹤碼。
- 不可重試的永久錯誤不再顯示誤導性的「重新處理」按鈕。
- 手機版 CTA 使用可換行 flex 版面，不依賴 hover 或桌機側欄。

## Review 發現與修正

1. 首頁原先連到帶狀態參數的資產庫，但資產庫沒有讀 URL 參數；已補齊初始化與 URL 同步。
2. 舊錯誤資料沒有 `retryable` 欄位；相容策略預設仍允許人工重試，只有明確 `false` 才隱藏。
3. correlation id 原本只存在資料庫，前端無法提供客服追蹤碼；API 已加上安全字串，不暴露 exception stack。
4. 表單簽核、單據審批等應用模組仍保留「審核」詞彙；本輪只統一核心 Input／Knowledge 的人工作業，避免誤改不同業務語意。

## 驗證證據

- `vitest` 首頁、資產庫、資產詳情：7 passed。
- `tsc -b`：通過。
- 資產 API focused suite 於 I9-3 已通過；本階段補充 correlation id contract assertion。

## 剩餘風險

- I9-5 仍需將大量候選內容依原始來源分組，否則人工確認頁雖然用詞正確，資訊量仍過大。
- 正式 iPhone Safari 觸控與 viewport 需在部署後再次驗證。
