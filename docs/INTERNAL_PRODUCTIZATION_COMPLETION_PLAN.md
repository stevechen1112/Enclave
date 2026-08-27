# Enclave 內部產品化閉環計畫

**建立日期：** 2026-08-27
**適用基線：** 模組化多租戶、多模態企業知識平台
**目的：** 先完成所有不依賴客戶資料、客戶帳號、第三方簽核或外部測試單位的產品化工作，再把少數不可代勞項目保留為外部 GA gate。

---

## 1. 判定摘要

Enclave 已有可運作的正式環境與正式網域，也已具備完整的產品架構及大部分工程底座；目前不是「從功能原型開始」，而是進入產品化閉環階段。

| 層次 | 判定 |
|---|---|
| 架構與程式基線 | PASS；Phase B–M、F1–F3、UX-A–UX-D 已完成 |
| 正式服務存在 | PASS；`https://kachu.tw` 可用 |
| 正式站與目前工作區完全同版 | 尚未；正式站仍有 legacy knowledge routes，詳見 production browser acceptance |
| 內部產品化閉環 | 進行中；可由本團隊自行完成 |
| 商業 GA 外部閘門 | 尚未；只保留第三方、客戶與法律不可代勞項目 |

本計畫不把所有程式中的 `TODO`、provider stub 或實驗性 sidecar 都視為產品阻擋。只有屬於已宣稱產品能力、已啟用 deployment profile 或正式使用者路徑的缺口，才進入產品化 backlog。

---

## 2. 執行原則

1. 每個 Phase 必須有明確輸入、交付物、測試證據與 rollback 說明。
2. 每個完整 Phase 完成後先做獨立 Code Review；修完所有 Critical／High 問題才可進下一個 Phase。
3. 測試證據必須由可重跑命令產生，不能只記錄人工口頭結論。
4. 正式環境必須辨識 source commit、image digest、migration head、deployment manifest 與 frontend build，不能只看首頁是否能開。
5. 高風險知識、租戶隔離、刪除、回滾及權限測試一律 fail closed。
6. 外部 provider、Connector 或 Pack 未設定時必須明示 disabled／degraded，不得假裝完成。

---

## 3. 可完全由內部完成的 Phase

## Phase P0 — 發布版本一致性與可追溯性

**優先級：P0；立即處理**

**2026-08-27 狀態：** Implementation PASS；production activation HOLD。詳見 `PHASE_P0_RELEASE_PARITY_CODE_REVIEW.md`。

### 已有基礎

- Production CD、部署前備份與 edge health smoke 已存在。
- Deployment manifest、image identity 與 rollback gate 已有程式及測試。
- 正式首頁、Demo 登入及部分新版工作區已可用。

### 待完成

- Build 時產生不可變 release metadata：source commit、dirty state、backend／frontend image digest、deployment manifest id、migration head、OpenAPI hash、frontend route-contract hash。
- 由受保護 operations API 與「系統／版本更新」畫面顯示相同 metadata。
- 將 post-deploy smoke 從 `/health` 與首頁 200 提升為 authenticated canonical-route smoke：`/overview`、`/ask`、`/knowledge/assets`、`/knowledge/new`、`/knowledge/review`、品質頁、`/system/health` 與已啟用 Pack 的 `/job`。
- Smoke 必須核對 navigation manifest、API route availability 與 frontend bundle 是否來自同一 release。
- 部署失敗時輸出診斷、保留舊 image tag，禁止把 migration 已升級但 frontend 仍是舊 bundle 的狀態標記成功。
- 每次 production deploy 保存可機器讀取的 acceptance artifact。

### Gate

- 正式站與指定 release manifest 完全相符。
- Canonical routes 全部 PASS，未知／未授權路由依契約處理。
- Backend、worker、frontend、migration 不得混版。
- 產出 `PHASE_P0_RELEASE_PARITY_CODE_REVIEW.md` 後才能進 P1。

---

## Phase P1 — CI、供應鏈與安全自動閘門

**優先級：P0**

### 已有基礎

- Backend pytest、Ruff、frontend TypeScript／lint／build、Playwright、Docker build、pip audit 與 npm audit 已在 CI。
- SBOM 產生器、security findings gate 與安全掃描腳本已存在。

### 待完成

- 將 `frontend npm test` 納入 CI；目前 workflow 只有 TypeScript、lint、build 與 Playwright。
- 真正執行 backend type check；目前 CI 安裝 mypy，但沒有執行 gate。
- 加入 migration consistency、architecture authority、legacy surface、rollback 與 tenant isolation gates。
- 將 SBOM 生成與 artifact 保存納入 release build。
- 加入 secret scan、SAST、container image vulnerability scan 與 license policy gate。
- 對 lockfile、base image、第三方 action 與 sidecar image進行可重現 pinning 檢查。
- 高風險 finding 必須有期限、owner、例外簽核與阻擋規則。

### Gate

- PR 與 release CI 不需人工補跑關鍵測試。
- Critical／High security finding 為 0；例外必須有到期日。
- Release artifact 可追到 SBOM、source commit、test run 與 image digest。
- 完成 P1 Code Review 後才能進 P2。

---

## Phase P2 — 多租戶硬隔離與資料生命週期

**優先級：P0**

### 已有基礎

- 應用層 tenant ACL、RLS policy、shadow mode、tenant isolation tests 及 RLS rollout runbook 已存在。
- Asset tombstone、知識撤回、audit、資料匯出與刪除 runbook 已存在。

### 待完成

- 建立 production-like 非 superuser、無 `BYPASSRLS` 的 application DB role 測試環境。
- 自動掃描所有 tenant-owned tables；新增 tenant table 卻沒有 RLS policy 時 CI 失敗。
- 補齊跨租戶攻擊矩陣：ORM、raw SQL、background job、Redis key、object key、search、review、export、signed URL、Pack route、websocket／realtime。
- 驗證 request／task 多次 commit 後 RLS context 仍存在，缺 context 必須看不到任何 tenant row。
- 產生 shadow difference report；內部 staging 可先啟用 FORCE RLS 並跑完整回歸。
- 完整驗證 delete／retention／tombstone 後，資料不會從 cache、projection、索引、匯出或舊 evidence locator 復活。
- 為 break-glass／platform maintenance bypass 建立獨立身分、audit 與最小權限測試。

### Gate

- 所有跨租戶攻擊測試洩漏數為 0。
- 所有 tenant-owned tables 都有 machine-verified policy。
- Staging FORCE RLS 全量回歸 PASS。
- 刪除、撤回與保留政策端到端 PASS。
- 完成 P2 Code Review 後才能進 P3。

---

## Phase P3 — 多模態 Golden Corpus 與品質閘門

**優先級：P0**

### 已有基礎

- 文件問答已有 blind／holdout 架構與歷史 78–79% 基線。
- OCR、ASR、影片 ingestion、timeline、review 與 evidence 已有程式與測試。
- 目前尚無影片人工時間軸 ground truth，也沒有完整跨模態 sealed evaluation。

### 待完成

- 建立可合法保存在 repository 或受控 artifact store 的內部 golden corpus：原生／掃描 PDF、DOCX、XLSX、CSV、圖片、混排表格、安靜／噪音／多人／長時間語音，以及含字幕／無字幕、固定／手持、設備畫面的作業影片。
- 建立 ground truth schema：文字、表格欄位、speaker、時間碼、OCR 區域、步驟、條件、風險、例外、SOP conflict 與 evidence locator。
- 建立 provider matrix runner，區分 mock contract、internal live provider 與 degraded mode。
- 指標按資料類型分組，不用單一平均數掩蓋手寫、噪音或長影片弱點。
- 加入 hallucination、錯誤引用、跨版本混用、低信心未送審及高風險未拒答測試。
- 每次 parser、model、prompt、chunking 或 retrieval 變更都跑 sealed regression。

### 建議內部 Gate

- 支援格式 98% 以上進入正確且可解釋的 terminal state。
- Evidence locator precision 至少 95%。
- 高風險內容無正式依據仍直接回答：0 次。
- SOP conflict 漏攔截：0 次。
- 跨租戶 evidence 或檢索結果：0 次。
- 所有 regression 必須列出 per-slice 結果。
- 完成 P3 Code Review 後才能進 P4。

---

## Phase P4 — 故障注入、備份還原與營運閉環

**優先級：P1**

### 已有基礎

- Backup／restore、rollback verifier、fault recovery 與 sidecar chaos 腳本已存在。
- Prometheus middleware、alert rules、Sentry integration 與 support bundle 已存在。
- Rollback evidence template 目前仍是 `NOT_RUN` 空白範本。

### 待完成

- 在隔離環境實際執行 DB、object storage、索引與設定的 backup／restore drill。
- 演練 N-1 application rollback、migration compatibility scan 與新 artifact kind 保護。
- 故障注入 Redis、Celery worker、ASR／OCR／embedding provider、object store、ClamAV、DB connection、網路 timeout 與重複 job delivery。
- 驗證 job idempotency、retry budget、dead-letter／人工處理、進度恢復與 UI 錯誤訊息。
- 對每條 alert 做 fire／recover 測試。
- 自動產生包含 RPO、RTO、digest、operator、image 與 smoke 結果的 rollback evidence。

### Gate

- Restore 可在全新隔離環境重建服務，並通過 tenant isolation 與 sealed retrieval smoke。
- 實際 RTO／RPO 有紀錄且符合內部 SLO。
- 關鍵相依服務故障不造成資料遺失、跨租戶洩漏或假完成。
- 完成 P4 Code Review 後才能進 P5。

---

## Phase P5 — 效能、容量、成本與 72 小時穩定性

**優先級：P1**

### 已有基礎

- Locust、k6、concurrency stress 與故障恢復腳本已存在。
- API、query、task 與 business metrics 已有程式基礎。

### 待完成

- 定義 Lite／Standard／Enterprise 三種 profile 的容量模型與 SLO。
- 測試登入、資產列表、搜尋、問答、上傳、批次 ingestion、音訊與影片 queue。
- 以預估尖峰兩倍進行 load test，並跑 24–72 小時 soak test。
- 測量 DB pool、Redis、Celery backlog、object I/O、memory、CPU／GPU、provider latency 與失敗率。
- 建立每租戶、每 GB、每小時音訊／影片、每千次問答的成本報表與 quota guardrail。
- 明確定義慢 provider、quota 用盡、queue 飽和與 sidecar unavailable 的降級策略。

### Gate

- 各 deployment profile 都有可重跑的 capacity report。
- 預估尖峰兩倍下不發生資料錯亂或不可恢復 backlog。
- 72 小時 soak 無持續性 memory leak、連線耗盡或 queue 堆積。
- 成本超限會阻擋或降級，不會無上限消耗。
- 完成 P5 Code Review 後才能進 P6。

---

## Phase P6 — UI/UX、無障礙與裝置實驗室驗證

**優先級：P1**

### 已有基礎

- 六 persona、responsive workspace、手機入口及 isolated browser acceptance 已通過。
- Frontend 目前缺少明確的 automated accessibility test inventory。

### 待完成

- 加入 axe／ARIA／keyboard navigation／focus order／contrast 自動檢查。
- 建立 persona × capability × route contract E2E，驗證隱藏選單不能靠 deep link 繞過。
- 驗證 empty、loading、partial、failed、retry、offline、timeout、quota、provider disabled 與長任務恢復狀態。
- 使用內部 Android／iPhone／平板與桌面瀏覽器實測拍照、錄音、錄影、長時間上傳與中斷續傳。
- 使用合成工廠噪音與網路限速完成 internal lab 測試。
- 驗證 evidence deep link 能正確打開文件頁、圖片區域、音訊及影片時間點。
- 建立 visual regression 與核心頁面 performance budget。

### Gate

- 核心流程無 Critical／Serious accessibility violation。
- 所有 persona route contract PASS，未授權 deep link 不能顯示資料。
- 支援裝置矩陣、網路降級與 media capture 全部留下證據。
- 完成 P6 Code Review 後才能進 P7。

---

## Phase P7 — 租戶營運、模組生命週期與商業沙盒

**優先級：P2**

### 待完成

- 全新租戶 onboarding、首位 owner、部門／角色、知識庫、Pack binding 與 Demo 清除流程自動化。
- Pack 安裝、升級、停用、設定 migration、rollback、orphan data 與 entitlement 測試。
- Tenant export、刪除、保留、legal hold、audit export 與 support bundle 端到端驗證。
- Quota、用量、超額、帳單、付款 webhook replay／idempotency 以 sandbox 完成。
- 通知、email verification、MFA recovery、SSO mock IdP 與 domain policy 以內部環境驗證。
- 清除 stale TODO／過期文件與未啟用 provider stub 的誤導性產品宣稱。

### Gate

- 新租戶不靠工程師改 DB 即可建立、啟用、停用與匯出。
- Pack 不需要 fork core code；停用後 UI、API、job 與資料邊界一致。
- Sandbox billing／SSO／通知重送不造成重複 side effect。
- 完成 P7 Code Review 後才能進 P8。

---

## Phase P8 — 內部 Release Certification

**優先級：P2**

### 待完成

- 建立單一 `product_readiness_gate`，聚合 P0–P7 的 artifact 與結果。
- 自動輸出 release candidate、環境、commit、image、migration、測試、弱項、例外與 rollback 狀態。
- 對 capability claims、README、正式 UI、API 與實際 deployment flags 做一致性掃描。
- 產生 signed internal release decision：PASS／HOLD／FAIL。

### Gate

- 所有 P0–P7 為 PASS，或只有具 owner、期限與降級策略的非阻擋例外。
- Critical／High correctness、security、tenant isolation 與 data-loss 問題為 0。
- 才可宣稱「內部產品化完成」；商業 GA 仍需外部項目。

---

## 4. 不等待外部即可先做的替代驗證

| 外部項目 | 內部可先完成 |
|---|---|
| 真實客戶文件 | 合成＋公開授權＋內部去識別 golden corpus |
| 真實工廠噪音 | 噪音混合、回音、距離、多人與網路限速實驗室測試 |
| 真實 ERP／MES | Contract test server、record/replay、錯誤碼與 webhook simulator |
| SharePoint／Drive | Mock OAuth、token refresh、權限撤銷與增量同步 contract tests |
| 真實付款 | Sandbox checkout、notify replay、冪等與對帳測試 |
| 客戶 DR | 內部隔離 restore／rollback drill；客戶簽名仍留外部 |
| 客戶 UAT | 內部 persona task test、可用性與無障礙測試 |
| 第三方滲透 | 內部 SAST／DAST／dependency／container／secret scan |

---

## 5. 不可由內部自行關閉的外部 Gate

1. 獨立第三方滲透測試與修補複驗。
2. 法律、錄音錄影同意、資料跨境、模型／第三方授權與隱私條款簽核。
3. Design Partner 使用真實工作流與真實資料的 UAT 簽署。
4. 客戶現場真機、弱網、工廠噪音與實際設備流程驗收。
5. 客戶 ERP／MES／SharePoint／Drive 的正式憑證與權限驗收。
6. 真實商戶金流憑證與財務對帳。
7. 客戶環境 DR、RTO／RPO 與安裝交付簽核。

---

## 6. 建議執行順序

```text
P0 發布一致性
  → P1 CI／供應鏈
  → P2 多租戶硬隔離
  → P3 多模態品質
  → P4 故障／DR
  → P5 效能／成本
  → P6 UX／裝置
  → P7 租戶營運／商業沙盒
  → P8 內部產品認證
```

P0–P3 應先於新增更多 Domain Pack 或垂直功能。P8 只聚合證據，不替前面的測試補分。

---

## 7. 完成定義

```text
目前架構與功能基線
＋ P0–P8 內部 Gate 全部 PASS
＝ 內部產品化完成

內部產品化完成
＋ 第三方／客戶／法律外部 Gate 完成
＝ Commercial GA 可宣稱
```
