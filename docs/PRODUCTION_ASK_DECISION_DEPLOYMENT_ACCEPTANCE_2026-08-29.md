# Production Ask Decision Workspace deployment acceptance — 2026-08-29

## 結論

`https://kachu.tw` 已部署問答決策頁，正式 release 為
`production-ask-315d23d`。

- Source：`315d23d3fa10a09031cd9e9316f648c355fbc3c1`
- Release tag：`release-20260829-ask-decision-v1`
- Deployment manifest：`dm-47bb92341547ac5de299355f`
- Schema：`input_i8_pilot_evidence_001`（本次沒有 migration）
- Release source gate：PASS（644 個部署檔案、乾淨來源、無高信心 secret finding）
- Production smoke：15／15 PASS

## 發布保護

- 發布前建立並驗證 gzip 的資料庫備份：
  `/opt/enclave/backups/enclave_predeploy_315d23d_20260829T045829Z.sql.gz`
- 遠端主機逐檔比對 frozen deployment manifest 的 644 個檔案：PASS。
- Backend、Frontend、Gateway 皆由同一份已驗證來源建置，edge health 與
  `release.json` 的 release id、source commit、dirty state、manifest、schema 和
  route contract 均一致。

## 瀏覽器驗收

以正式站合成「主管唯讀」角色完成驗收，未新增資料、未送出提問、未上傳檔案。

- `/ask` 顯示「企業知識 · 答案決策頁」與新的空狀態。
- 對話記錄改為可開關抽屜，既有對話可唯讀載入。
- 已有回答會顯示目前問題、四段處理狀態、直接回答及證據數量。
- 證據以獨立抽屜顯示，包含可核對的文件與定位連結；可正常開關。
- 桌機 1280×720 與窄螢幕 390×844 均無水平 overflow。
- 問答頁 console error／warning 為 0。

## 未解除的產品 gate

本次是問答體驗的正式發布與回歸驗收，不改變既有的商業宣告：第一個真實租戶仍應採受控
Pilot／專屬 deployment 或資料庫；共享多租戶 GA、SLA、真機弱網與現場驗收仍維持既有 HOLD。
