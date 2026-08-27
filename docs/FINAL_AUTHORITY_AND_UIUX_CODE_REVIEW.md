# 架構權威收斂與 UI/UX 重構：最終 Code Review

**Review date:** 2026-08-27
**Reviewed scope:** Phase H–M
**Implementation gate:** PASS
**Legacy removal authorization:** HOLD（未執行刪除）

## 結論

本輪已把系統收斂成三個穩定根基與可選應用層：tenant isolation、企業
Knowledge Core、多模態 Ingestion Platform，以及由 Pack 貢獻的 domain
workflow／UI。文件、表格、圖片、音訊、影片、URL 與 connector record
共用 SourceAsset identity、ingestion lifecycle、ACL、review、KnowledgeUnit
release 與 evidence contract；MKA 是第一個可選 Domain Pack，不再反向成為
Base 平台的產品或導覽權威。

未發現仍阻擋本架構基線進入 staging 的 Critical／High correctness 或
authorization 問題。舊介面的實際 disable/remove 沒有獲准：現有觀察窗只
經過一天，且本機空白 rollback 模板不是操作人員演練證據。

## 最終 review 修正

1. 全部 `/api/v1` 原先會被籠統標示升級；現在只有 registry 中的精確舊
   API 才收到 `Deprecation`、successor `Link`、stage，以及 warn 後的
   `Sunset`／`Warning`。穩定 v1 只回報 API version。
2. 舊 API 只統計前端 redirect，無法證明 SDK／自建 client 已停用。現在
   authenticated legacy API response 也寫入 tenant-scoped audit stream，
   telemetry 失敗不影響原請求。
3. 原始 retirement 判斷容易把「沒有資料」誤當零流量。簽章報告現在要求
   active tenant 非空、完整列舉、至少 30 天、合法 stage，observe 永遠不
   可 removal。
4. 初版階段授權以所有 surfaces 的總狀態決定，會讓不相關應用互相卡住。
   現在每次必須指定一個 surface，逐 tenant 核對該 surface 的唯一證據、
   registry 現況與連續階段，不能跳級或反向。
5. disable/remove 缺少可機器驗證的 rollback evidence。現在 fail-closed
   gate 驗證部署 image identity、DB／object backup digest、隔離 restore、
   migration downgrade、新 artifact kind 相容掃描、durable object 清單、
   四組 smoke tests 與具名 operator attestation。
6. 舊 `/documents` bookmark 一度仍導向專用 DocumentsPage。現在正式導向
   統一 `/knowledge/assets`；既有 `/knowledge/documents/:id` evidence 深連結
   仍保留相容，不在本輪破壞可追溯引用。
7. 實際 browser gate 發現 `/login` 無條件只顯示 Demo 六道門，正式租戶
   無帳密入口；錯誤帳密的 401 也會被全域 interceptor 誤當成 session
   過期並 reload。現在正式帳密表單是主入口，Demo 只在 server 回報啟用
   時揭露，登入請求的 401 留在表單呈現可及的錯誤訊息。

## 架構與安全結果

- Canonical read authority：KnowledgeUnit／Release 決定可搜尋與發布狀態，
  Asset ACL 與 provider visibility 在讀取時重新驗證；legacy document、
  video、know-how 只作 projection／compatibility source。
- Pack 邊界：Base 不靜態註冊 MKA routes；API、worker、review provider、
  UI module 與 capability 由同一 composition root 組裝。關閉 pack 後不留下
  navigation、route 或 action。
- UI 權威：角色 capability、primary navigation 與 default home 由 server
  bootstrap 決定。前端未載入或 bootstrap 失敗時 fail-closed，不含完整
  role fallback table。
- 統一體驗：新增知識、Asset Library、processing timeline、Review Inbox、
  Evidence Workspace 與角色首頁不要求使用者理解底層 parser／ASR／OCR／
  worker 名稱。
- 影片治理：原檔 hash／ACL、音影分離、ASR／speaker／timecode、scene／
  keyframe／OCR、動作與異常聲音候選、跨模態對齊、程序／風險／例外、
  SOP conflict、人員覆核與 published KnowledgeUnit 均保留 evidence locator。
- 相容退場：24 個 frontend/API surfaces 目前皆為 observe；階段變更工具只
  產生 PASS/HOLD 決策，不自行修改 registry、route、schema 或資料。

## 驗證證據

- Backend full regression：**1,211 passed**, 0 failed，7 個既有第三方
  dependency deprecation warnings，311.59 秒。
- Frontend：**22 test files / 76 tests passed**；ESLint 與 TypeScript/Vite
  production build 通過。
- Chromium Playwright：在 fresh、隔離、升級至 head 的暫存 PostgreSQL
  環境中 **10/10 passed**；涵蓋正式登入、匿名 fail-closed、server home、
  Asset Library、legacy redirects、intake、review、command palette 與 API
  deprecation metadata。測試服務及暫存資料庫於驗證後移除。
- Focused Phase M／authorization suites：**43 passed**。
- PostgreSQL：Alembic current 為 `knowledge_authority_h1_012 (head)`；
  `alembic check` 回報無新增 migration。
- API inventory：**332 routes，0 duplicate method/path**。
- Python compileall、Phase M Ruff 與 `git diff --check` 通過；diff check 只有
  Windows LF→CRLF 提示，沒有 whitespace error。
- 本機 active-tenant signed-report rehearsal：列舉 **334 tenants**，狀態
  `HOLD`、exit code 3；測試用簽章報告隨即由 temp 目錄移除。
- 空白 operator rollback evidence：狀態 `HOLD`、exit code 3，完整列出
  deployment、backup、restore、downgrade、object inventory、smoke 與
  attestation 缺件。

## 退場決策與下一個不可跳過的 gate

目前不得刪除 compatibility routes/APIs、legacy schemas 或 object-store
內容。最早日期也不能只由日曆推定；必須確保 telemetry 全程健康，且每次
命中都會重啟該 tenant／surface 的 30 天零流量判斷。

部署團隊後續應針對單一 surface 依序執行：tenant notice 與 SDK migration、
`observe → warn`；取得涵蓋所有 active tenants 的有效簽章報告後才可
`warn → disable`；完成具名 backup/restore 與 N-1 rollback drill 後才可
`disable → remove`。實際移除必須是獨立 PR，且不得與首次 route removal
同版刪除 durable data。

## Gate decision

Phase H–L 與 Phase M 的相容／驗證機制通過 code review。整體重構基線可
進 staging canary；legacy removal gate 維持 HOLD，這是目前唯一正確且
安全的結果。
