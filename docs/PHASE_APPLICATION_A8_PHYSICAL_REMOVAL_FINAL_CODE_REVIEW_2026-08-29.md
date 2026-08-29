# Phase Application A8：物理排除與最終驗收 Code Review

**日期：** 2026-08-29

**結論：** PASS（程式、測試與本地瀏覽器驗收）

**部署狀態：** 本文件不代表這批變更已部署到正式網域

## 1. 本階段完成內容

- composition 改為只 import 本次部署啟用的 Pack；停用不再只是註冊後隱藏。
- 新增 `PACK_SALES_QUOTE_ENABLED`、`PACK_INCIDENT_HANDOVER_ENABLED`、
  `PACK_QUALITY_8D_ENABLED`、`PACK_TRAINING_KNOWHOW_ENABLED` 四個獨立部署旗標。
- 保留 `PACK_MKA_ENABLED` 作為舊部署總開關；新旗標未設定時沿用總開關，避免升級後意外啟用應用。
- 四個應用逐一排除，驗證其 manifest 在 fresh process 中不會被 import，其他應用與核心仍存在。
- 三個 deprecated Pack import bridge 歸零：
  - `app/api/v1/endpoints/knowhow.py`
  - `app/api/v1/endpoints/voice.py` 對 training persistence 的依賴
  - `app/services/mka_persistence.py`
- 核心語音互動 persistence 移到 `app/services/interaction_repository.py`，核心 Input 不再依賴訓練 Pack。
- Know-how 與訪談 endpoint 移入 `training_knowhow` Pack。
- 報價 Realtime Voice endpoint 移入 `sales_quote` Pack，並新增自己的 API contribution。
- 音訊保存政策 API 改由核心 API 提供，不再隨訓練 Pack 被拔除。
- 長錄音轉寫／音訊 retention 移入核心 Input worker；表單匯出移入核心 Workflow worker，兩者不再依賴 training Pack 才註冊 Celery task。
- 移除 MKA shell 中重複的 know-how provider／review implementation。
- 修正 A7 後遺留的舊 route key：`mka.job.home` 改為 `workflow.job.home`，避免導覽顯示 `/job` 但進入後被導回總覽。

## 2. 物理排除矩陣

| 排除 Pack | 不應存在 | 其餘能力 |
|---|---|---|
| `sales_quote` | quote handler、sales UI、Realtime Voice API、manifest import | incident、8D、training 與核心保留 |
| `incident_handover` | incident handler、manifest import | quote、8D、training 與核心保留 |
| `quality_8d` | 8D handler、manifest import | quote、incident、training 與核心保留 |
| `training_knowhow` | know-how API/UI/provider/review/handler、manifest import | quote、incident、8D 與核心 Input 保留 |

另驗證 base-only、sales-only、training-only 組合。獨立旗標控制的是部署可用性；
租戶能否使用仍由 `TenantModuleBinding`、生命週期與權限共同決定。

## 3. 測試證據

- Backend 最終全量：1,553 collected；1,541 passed、12 skipped、0 failed。
  Docker 權限項已納入同一次乾淨 gate；公平排程 assertion 已改為驗證 round-robin 性質而非隨機 UUID 先後。
- Backend A8／Pack／設定／Realtime／tenant boundary 目標測試：59 passed。
- Frontend ESLint：PASS，0 error。
- Frontend Vitest：37 files、124 tests passed。
- Frontend production build：PASS，3,356 modules transformed。
- `git diff --check`：PASS。

## 4. 瀏覽器驗收

使用本地最新程式與合成 Demo 租戶檢查：

- 桌機：登入、總覽、`/knowledge/new`、`/ask`、`/job`、`/knowhow`。
- Input 四種來源：檔案、現場擷取、網址、外部紀錄。
- 現場擷取：拍照、錄音、錄影入口與同意／保留政策提示。
- 問知識：A 款問答版型、對話、證據、新對話與輸入區。
- 應用：Workflow 工作區與 training know-how 路由正常；無權限的 quote 任務 fail closed。
- 手機 390×844：Input 與 Ask 版面、行動拍照／錄音／錄影入口可見且無水平破版阻斷。
- Browser console：0 error、0 warning。

瀏覽器驗收發現並完成修正 `workflow.job.home` capability 對齊問題，重驗 `/job` 通過。

## 5. Code Review 結論

### 已關閉

- 核心 Voice → training persistence 的反向依賴。
- training Pack 誤擁有報價 Realtime Voice 與核心 audio policy。
- 停用 Pack 仍先 import implementation 的假排除。
- 舊 endpoint／service import bridge。
- A7 route key 改名後的 UI 導覽／權限不一致。

### 保留但非 A8 blocker

- `app.models.mka` 仍是歷史資料表模組；這是 schema／migration 相容邊界，不代表應用 runtime 再度聚合。
- 前端獨立 bundle 由 `frontend/src/modules/installed.ts` 作 build-time composition；若產品 SKU 要連 optional chunk 都不配送，需在該 composition root 排除對應 bundle。
- 本次完成的是本地程式與驗收；正式網域仍需走既有 release、migration、smoke、parity 與 rollback gate。

## 6. 判定

A8 通過後，可以宣稱四個現有場景應用在後端 Pack、Workflow handler、API ownership、
前端 bundle 與租戶 entitlement 上已分離，且核心 Input／Knowledge／Ask／Workflow 不依賴任一場景應用。
不能把此結論延伸為「所有場景產品設計都已驗證」或「最新提交已部署正式環境」。
