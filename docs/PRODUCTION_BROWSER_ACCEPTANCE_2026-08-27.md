# Production Browser Acceptance — 2026-08-27

**Target:** `https://kachu.tw`
**Method:** in-app Chromium，正式六門 Demo 的「公司管理」persona
**Decision:** 正式服務與新版體驗部分 PASS；目前工作區最新 modular baseline parity 為 HOLD

## Verified

- HTTPS 正式首頁可載入，標題為「Enclave｜製造業知識作業平台」。
- 公開首頁、六個 Demo 角色入口與展示環境警語可見。
- 「公司管理」Demo 可進入 `/overview`，顯示新版主要導覽：總覽、現場作業、問答、知識、管理、系統。
- `/job`、`/knowledge/review`、`/system/health` 可載入。
- 本輪檢查未發現 browser console error／warning。

## Release parity findings

- 正式站主要「知識」導覽仍進入 `/knowledge/documents`，子導覽仍是文件、知識頁、來源、審核、品質。
- 直接開啟目前工作區 canonical routes `/knowledge/assets`、`/knowledge/new`、`/knowledge/coverage` 會回到公開首頁。
- 正式 frontend bundle 為 `index-DJhxiLjt.js`／`index-CLGsq5N3.css`；本機最近 build 的主要資產名稱不同。
- 因此可以證明「正式網域已有產品服務」，但不能證明「目前工作區最新 modular baseline 已完整部署」。

## Required next action

先完成 `INTERNAL_PRODUCTIZATION_COMPLETION_PLAN.md` Phase P0：在 release 中加入不可變 build metadata，並讓 deployment workflow 執行 authenticated canonical-route smoke。未通過前，production parity 維持 HOLD；這不代表正式服務離線。
