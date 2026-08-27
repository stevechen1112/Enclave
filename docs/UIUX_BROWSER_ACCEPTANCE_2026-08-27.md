# UI/UX 瀏覽器驗收紀錄

**日期：** 2026-08-27
**環境：** 隔離本機 PostgreSQL 租戶、Redis、API、Celery、Vite
**結果：** PASS（產品介面與權限）；外部模型／實體媒體裝置另列環境驗收

## 驗收範圍

- 公開首頁、六道 Demo 入口、登入成功與失敗、登出。
- Owner 的總覽、問答、Knowledge Workspace、治理與系統管理頁。
- Asset Library、統一新增知識、Asset Detail、Review、來源、品質、知識頁。
- 文件與試算表多檔加入、處理狀態、失敗說明與重試。
- 舊網址轉址：`/documents`、`/audit`、`/query-analytics`。
- 命令搜尋的開啟、輸入焦點、Escape 關閉與焦點復原。
- 業務、設備現場、班長／師傅、新人、主管唯讀、公司管理六種角色。
- 角色邊界：主管唯讀不可新增知識；新人不可建立師傅訪談；師傅可進入訪談錄音。
- 390×844 手機尺寸的工作台、側欄、問答與新增知識，包含水平溢位檢查。
- 瀏覽器 console error 檢查。

## 瀏覽器發現並完成修正

1. Asset Library 無結果時出現兩個「清除篩選」：收斂為單一操作並補測試。
2. canonical `active` 資產短暫顯示「未知」：補齊生命週期正規化映射。
3. 失敗事件使用完成圖示、處理階段未中文化、直接暴露底層連線訊息：改為紅色失敗事件、中文階段及安全可行動提示。
4. Job Workspace 掛載後再次刷新 bootstrap，與 ProtectedRoute loading gate 互相觸發，造成無限請求及永遠載入：移除重複刷新並加入 regression test。
5. 直接重新載入 `/job` 時，server manifest 尚未返回，wildcard route 先把使用者送回首頁：在動態模組路由建立前保留原 deep link。
6. 問答與師傅訪談頁缺少頁面級 H1：補上正確 heading hierarchy。

## 驗收結果

- 公開首頁與一般登入：PASS。
- Owner 核心平台與所有 Knowledge Workspace 子頁：PASS。
- 六種 Demo persona 登入、職能工作台與權限隔離：PASS。
- 多租戶測試資料只出現在各自租戶：PASS（隔離資料庫與 tenant-scoped API）。
- 手機工作台、問答、選單、拍照／錄音／錄影入口與新增知識：PASS；頁面寬度未溢出 viewport。
- legacy deep link 與動態 Pack `/job` deep link：PASS。
- browser console error：0。
- Frontend：23 files／83 tests passed；lint 與 production build passed。
- Backend demo、experience、Pack runtime、provider registry：38 tests passed。

## 外部環境邊界

本輪實際上傳 `manual_text.txt` 與 `torque_table.csv`，資產建立、排程、失敗呈現及重試均通過。隔離環境未啟動 Ollama embedding endpoint，因此背景處理按設計進入 `failed`；這驗證了降級與錯誤 UX，但不等於 embedding 成功驗收。

下列項目仍需在具備服務與裝置的部署環境驗證：

- Ollama／正式 embedding provider 的成功索引與可搜尋答案。
- 真實手機的相機、麥克風、長時間錄音、鎖屏／切換 App 行為。
- ASR、說話者、OCR、鏡頭切分、關鍵幀與跨模態時間軸的真實影片全鏈路。
- 正式外部模型的回答品質、citation deep link 與高風險 SOP conflict 人工覆核。

以上是部署／供應者 acceptance gate，不是本輪瀏覽器發現的未修 UI 阻斷問題。
