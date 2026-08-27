# 模組化多租戶知識平台：最終整合 Code Review

**Review date**: 2026-08-27
**範圍**: Phase B–G 與影片 F1–F3
**Gate result**: PASS（附帶明確的營運觀察窗與專業模型邊界）

## 結論

本輪架構調整已形成可維護的四層責任邊界：多租戶平台、企業知識核心、多模態 ingestion，以及可選 Domain Packs／前端模組。既有 MKA 場景保留向後相容，但不再是核心檢索與平台契約的硬依賴。影片知識從來源、衍生物、證據、候選程序、SOP 衝突到人工發布均保留租戶、版本與時間證據鏈。

未發現阻擋合併的 Critical／High 問題。最終審查期間另修正兩項交付一致性問題：補齊所有 `VIDEO_*` 部署範本；移除主架構文件中已過期的「尚未開始影片處理」施工描述。

## 架構與安全檢查

- Asset identity 以 `SourceAsset → AssetRevision → DerivedArtifact → EvidenceSpan` 表達，來源與衍生知識不混寫。
- 所有新增讀寫、背景工作、SOP 載入、媒體資源與 legacy telemetry 均帶 tenant 條件；資料庫 migration 建立複合 tenant foreign keys。
- 瀏覽器影音採短效、scope 與 resource-bound token；原檔與關鍵幀不暴露可猜測的 storage key。
- 影片上傳在 API 與 worker 兩側驗證，包含容器、codec、大小、時長、解析度、malware scan、hash 與 worker re-probe。
- 程序候選預設不可搜尋；只有 owner／admin／superuser 人工核准、處理所有 SOP 衝突並確認高風險後，核准版本才進入 video knowledge provider。
- 正式 SOP 優先權由發布時不可變 `ArtifactReviewDecision.resolution_json` 保存；檢索不會讀取未核准候選內容。
- Pack 部署旗標只表示環境能否承載；租戶 `TenantModuleBinding` 仍是實際授權權威，API、retrieval、route、navigation 與 workspace 使用同一 eligibility decision。
- FastAPI 319 個 routes 沒有重複 method/path；重複 `/job-modules` GET 已合併為單一 canonical contract。

## 影片管線對照

1. 匯入、SHA-256、資料分類、ACL 與版本 identity。
2. ffprobe policy revalidation；ffmpeg 音訊分離。
3. timestamped ASR；說話者能力由 provider 狀態明確表示。
4. scene boundary、關鍵幀與 OCR artifact。
5. 有原文／OCR 證據的動作與設備候選；本機聲學離群候選不宣稱故障語意。
6. transcript、frame、OCR、scene、事件跨模態時間窗與一對多 EvidenceSpan。
7. 步驟、前置條件、判斷規則、風險、例外、禁止動作與適用機台／角色。
8. 人工覆核、正式 SOP 當前版本與 chunk 級衝突證據、SOP precedence。
9. 核准後以 published procedure 進入 tenant-scoped retrieval；回答可回到影片時間點。

## 驗證證據

- Backend 全量：`1169 passed`，最終重跑耗時 319.45 秒。
- Frontend：`69 passed`；production build 與 ESLint 通過。
- PostgreSQL fresh schema：Alembic 位於 `video_governance_f3_011 (head)`，`alembic check` 無待產生 migration。
- Migration：Phase B、C、F1、F2、F3 均完成 upgrade／downgrade／re-upgrade roundtrip。
- Application route inventory：319 routes，0 duplicate method/path。
- 本輪新增／重構 Python 範圍的 Ruff、Python bytecode compilation 與 `git diff --check` 通過；僅有 Windows 工作區 LF→CRLF 提示。
- 各 phase 的獨立 review 證據存於 `docs/PHASE_*_CODE_REVIEW.md`。

## 有意保留的限制與後續 gate

- 專用視覺動作、設備狀態、語意異音故障與高品質 diarization 尚未綁定特定模型。內建能力只產生可追溯候選，UI/API 不把候選包裝成確定診斷。
- 影片 holdout 與人工時間軸 ground truth 尚未建立，因此本輪只宣稱管線與治理完成，不宣稱跨產業辨識準確率。
- 16 個 legacy frontend routes 正在 observe；此前缺乏可信逐租戶流量證據，現在移除會違反退場政策。任何 removal PR 仍須滿足逐租戶 30 天零流量、公告、disable 與回滾演練。
- 既有相依套件仍輸出 `pkg_resources`／jieba／pyannote 類棄用警告，不影響本輪測試結果，但應另立 dependency maintenance 工作處理。

## 發布建議

可將本輪變更作為單一架構基線進入 staging。正式生產啟用影片前，需確認 ffmpeg／ffprobe、物件儲存、malware scanner、Celery worker、ASR／OCR provider、配額與 `VIDEO_*` 限制皆已按部署環境設定；先以少量租戶 feature flag 漸進啟用並觀察處理時間、成本、人工駁回率與 SOP 衝突率。
