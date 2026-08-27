# Production Browser Acceptance — 2026-08-27

**Target:** `https://kachu.tw`
**Release:** `gh-33065429723-1` / `a86644d3412e75d4d855a8217d3b166ad031aa21`
**Method:** machine parity script、production Playwright、in-app browser，正式六門 Demo 的「公司管理」persona
**Decision:** PASS

## Verified

- HTTPS 正式首頁可載入，標題為「Enclave｜製造業知識作業平台」。
- 公開首頁、六個 Demo 角色入口與展示環境警語可見。
- 「公司管理」Demo 可進入 `/overview`，顯示新版主要導覽：總覽、現場作業、問答、知識、管理、系統。
- `/overview`、`/ask`、`/knowledge/assets`、`/knowledge/new`、`/knowledge/review`、`/knowledge/quality`、`/system/health` 與 `/job` 均可在登入狀態下開啟。
- 「新增知識」清楚提供檔案、照片、錄音、影片、網址與外部紀錄入口，並顯示分類、處理、覆核與發布生命週期。
- 「證據審核」顯示風險、低信心、政策、證據與發布決策；「品質與版本」顯示正式版本與回滾語意。
- 「功能開關」把平台能力、應用模組、部署、租戶授權、執行狀態及使用者權限分開呈現。
- 「版本更新」顯示前後端一致、clean source、`knowledge_authority_h1_012` schema head 與正式 release ID。
- `/job` 顯示語音輸入、QR 掃描及可組合的現場／報價／知識工作入口；`/ask` 顯示證據抽屜與無證據不可視為確定事實的提醒。
- 本輪 in-app browser 未發現 console error。

## Release parity evidence

- `/release.json` 與 `/health` 的 release id、source commit、dirty state、schema head 及 route-contract hash 完全一致。
- Backend、worker、worker-beat 與 frontend 實際 container labels 均為 `a86644d3412e75d4d855a8217d3b166ad031aa21`。
- Web、worker、frontend health 為 healthy；worker-beat 為 running；Alembic 為 `knowledge_authority_h1_012 (head)`。
- `python scripts/verify_release_parity.py --base-url https://kachu.tw`：PASS，0 errors。
- `RELEASE_PARITY_E2E=true` production Playwright：3/3 passed（包含 direct deep-link shell 與 authenticated SPA routes）。

## Follow-up findings

- Gateway 的 general API per-IP burst limit 在連續 hard reload 測試中會回 503；企業 NAT 場景應在 P1 重新校準，並與 backend 的 per-user／per-tenant 429 策略整合。
- Frontend 初始 `/users/me` 遇到 503 時會清除 token；P1 應改成只有明確 401 才結束登入，暫時性錯誤顯示可重試狀態。
- GitHub Actions 顯示 Node 20 action runtime deprecation warning；P1 更新 action major versions。
