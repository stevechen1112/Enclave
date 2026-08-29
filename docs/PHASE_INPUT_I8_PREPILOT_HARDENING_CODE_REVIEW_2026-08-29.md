# Input I8 Pre-Pilot Hardening Code Review（2026-08-29）

結論：**ENGINEERING PASS / AUTHENTICATED VISUAL REVIEW PENDING / FIELD PILOT HOLD。** I8 已從只能建立、啟動與監看 gate，補成可在產品內完成證據登錄與 Incident 結案的操作工作台；完整自動化回歸通過。登入後人工視覺巡檢尚未取得本次瀏覽器登入授權，真實租戶 14–28 天 Pilot 亦未開始。

## Review 身分

- 工作樹基線：`d85b1503e1058ec4865d3f21a4477a363205c351` 加 Input I0–I8 未提交工作樹。
- Schema revision：`input_i8_pilot_evidence_001`，本次無 schema 變更。
- Pilot route SHA-256：`d8dd384062e738f631cd0b4918839c3d2256028451fa6aab9a7e55b8edbf812a`。
- Evidence workbench SHA-256：`b4ebdbe3237e056da2b6c90eb96f974df8a3bbc90d6426796251121671c508b0`。
- 未部署 production。

## 完成範圍

- 新增 tenant-scoped `GET /operations/input/pilots/{pilot_id}/evidence` operator view。
- 工作台可登錄每 journey 每日指標與來源 SHA-256。
- 可建立 data loss、越權、假完成與 near miss Incident。
- 未結 Incident 可填 root cause、corrective action、retrospective SHA-256 後結案。
- 可登錄 quality、security、permission Audit 與抽樣數、結果、證據 hash。
- 可封存不可覆寫的整體 Pilot retrospective。
- 可登錄 accepted／rejected 客戶簽署文件、授權角色、聲明、時間及 hash。
- running 以外狀態全面唯讀；ready 僅能先啟動。
- 本地時間輸入在送往 API 前轉為 UTC ISO，避免台灣時區被誤判為 future evidence。
- 表單提供 hash pattern、數值下限、Incident 結案完整度與不可覆寫說明。

## Code Review 發現與修正

1. **P1：原 I8 UI 無法操作 evidence lifecycle。** 雖然 API 完整，但實際 Pilot 只能靠工程人員呼叫 API。已建立完整 evidence workbench。
2. **P1：Acceptance UI 直接看完整 gate，簽署前必然因缺簽署而 HOLD。** 改為只排除 `signed customer acceptance is missing` 計算 preflight readiness；後端仍在寫入前重新執行權威 preflight。
3. **P1：瀏覽器 `datetime-local` 無時區，直接傳送會被後端視為 UTC。** 現在依使用者本地時區轉換為 UTC ISO。
4. **P2：UI 仍允許 hold 狀態重新 start，但後端已改為僅 ready。** UI 與後端狀態機已對齊。
5. **P2：Incident 結案按鈕可在欄位不完整時送出。** 現在 root cause、corrective action 與有效 SHA-256 齊備才可操作。

修正後無已知 P0／P1 程式碼缺陷。

## 驗證結果

- I8 backend focused：9 passed。
- I6–I8、tenant boundary、ACL、upload、queue、capacity、DLQ related regression：126 passed。
- 完整 backend：1,500 passed／12 skipped／0 failed。
- Frontend：36 files／121 tests passed。
- TypeScript `--noEmit`：PASS。
- Scoped ESLint：PASS。
- Vite production build：PASS；`InputPilotPage` chunk 25.29 kB、gzip 6.77 kB。
- Scoped Ruff、compile、JSON 與 `git diff --check`：PASS。
- 本機 API 與 Vite 啟動：PASS；`/health` database ready，登入頁正常。
- Authenticated browser visual/interaction pass：PENDING；未在沒有明確登入授權時輸入測試帳密，暫時服務已關閉。

## 剩餘 Gate

- 登入後桌面與窄螢幕的人工視覺、keyboard、screen-reader／axe 巡檢。
- 真實第一租戶環境、DPA、2–3 journey 與 14–28 天 evidence。
- 真實 quality/security/permission audits、Incident 復盤及客戶簽署。
- I7 live capacity/degradation/72h soak。

因此本次 hardening 工程通過，但 I8 field gate 與 Commercial GA 仍維持 HOLD。

## Production deployment follow-up

2026-08-29 已部署 `production-e34477b86f0e`，schema 為
`input_i8_pilot_evidence_001`。正式網域驗證 15／15 PASS；合成公司管理角色的
登入後桌面與 390×844 窄螢幕巡檢 PASS，console error／warning 為 0。

此結果解除本報告原列的「登入後人工視覺巡檢」待辦，但不等同真實第一租戶
Pilot、實體 iPhone／Android 驗證或 14–28 天 field evidence。
