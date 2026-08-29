# Production Input I8 deployment and browser acceptance — 2026-08-29

## 結論

`https://kachu.tw` 已完成 Input I0–I8 正式部署與登入後瀏覽器驗收。

- Release：`production-e34477b86f0e`
- Source：`e34477b86f0e4f4cb2d0130345283395ba1b5f88`
- Deployment manifest：`dm-472e96750fe3c8e6986295c8`
- Schema：`input_i8_pilot_evidence_001`
- Route contract：`5af2bf671476e71a40b148d374217000cf5271c648b6a96e7632e5ddb525b69f`
- Production verification：15／15 PASS
- Engineering decision：PASS
- Field Pilot／Commercial GA：仍為 HOLD

## Release 與備份證據

乾淨 source gate PASS，candidate images：

- Backend：`sha256:d2c50adc3ee43eb16f73b6d29231c65f1c82a7a2d01502768a9c4e778ecf959a`
- Frontend：`sha256:f222b12cbacb04e92b42ef58dda43b6c47fee036b72fa3bf7485f1abc41e467a`
- Gateway：`sha256:d0eb807d5809eb2ec2c48bc19603c40656e28474ca99736da89f2cfb63386cd7`

切換前新增且驗證的 DB 備份：

`/opt/enclave/backups/enclave_predeploy_e34477b_20260829T003400Z.sql.gz`

備份 gzip 完整性 PASS，大小約 892 KiB；既有備份未清除。

## Migration gate

舊 head `p5_cost_guardrails_001` 到新 head
`input_i8_pilot_evidence_001` 共渲染 427 行 SQL。部署前掃描未發現：

- `DROP TABLE`
- `DROP COLUMN`
- `TRUNCATE`
- `DELETE FROM`

Migration 以 PostgreSQL transactional DDL 套用完成。部署後 Alembic 唯一 head
為 `input_i8_pilot_evidence_001`，edge health 回報 database ready。

Production 目前有 110 張 RLS-enabled table、0 張 FORCE-RLS table；第一個真實
租戶仍應採專屬 deployment 或 database，不得據此宣稱共享式多租戶 GA。

## 部署期間攔截與修正

第一個候選 frontend Docker build 因兩個 Vitest 檔案未明確匯入
`describe／it／expect` 而 fail closed。修正後重新執行：

- Focused tests：2／2 PASS
- Full frontend：36 files／121 tests PASS
- ESLint：PASS
- TypeScript：PASS
- Vite production build：PASS
- Clean frontend Docker build：PASS

失敗候選映像未部署；正式站只切換到修正後的 r2 release。

Preflight 使用不同 Compose project path 時曾使 DB dependency 被 Compose 重建。
資料 volume 未變更，edge health 隨即恢復，且正式備份在 migration 前完成。後續
offline SQL render 應使用 `docker compose run --no-deps`，或固定從 canonical
`/opt/enclave` project path 執行，避免不必要的 dependency reconcile。

## 登入後瀏覽器驗收

使用正式站免密碼的合成「公司管理」角色，未輸入真實帳密、未新增 Pilot、未上傳
檔案，也未寫入正式資料。

PASS 項目：

- `/overview` 正常載入，知識健康與快速入口可見。
- `/knowledge/new` 即時顯示 30 種可處理格式、2 種降級格式與租戶剩餘配額。
- 上傳檔案、現場擷取、貼上網址、外部紀錄四個 tab 均可操作與切換。
- 現場擷取顯示拍照、錄影、錄音同意、30 秒安全保存、60 分鐘上限與 90 天保留資訊。
- 治理欄位包含資料分類、部門與現場脈絡。
- `/knowledge/assets` 可依文件、圖片、音訊、影片、網頁與外部紀錄等類型篩選。
- `/knowledge/sources` 正確標示 NAS 已認證，SharePoint／Google Drive 尚未認證。
- `/system/input-pilot` 正常顯示無 Pilot 空狀態與建立入口。
- 桌面與 390×844 窄螢幕無水平 overflow。
- 所有受測頁面 console error／warning 為 0。

因正式合成租戶沒有 Pilot，未透過瀏覽器建立資料來展示 evidence workbench；該工作台
的建立、指標、Incident、Audit、retrospective 與 acceptance 流程由 121 項前端測試
及 I8 backend tests 覆蓋。真實工作台仍須在第一租戶 Pilot 中累積 field evidence。

## 未被本次驗收解除的 gate

- 真實第一租戶 14–28 天 Pilot
- iPhone Safari／Android Chrome 實機與弱網測試
- I7 live capacity、degradation 與 72 小時 soak
- 客戶 DPA、品質／安全／權限稽核、Incident 復盤與簽署驗收
- Production application role 切換與 FORCE RLS rollout
