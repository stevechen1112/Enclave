# Phase UX-D Pack UI Contract Code Review

**日期：** 2026-08-27
**決策：** PASS

## 範圍

- Frontend bundle 必須宣告唯一 `bundleKey` 與封閉的 `ownedRouteKeys`。
- Registry 啟動時檢查非法 bundle、跨 bundle route 及重複 ownership。
- Server manifest 先與 bundle ownership 取交集；未知 route fail-closed。
- 補充 Pack UI 維護規格與角色型 manifest tests。

## Review 結果

- build-time composition root 只宣告安裝哪些 bundle，不保存租戶 entitlement。
- authenticated server bootstrap 仍是 route/navigation 啟用權威。
- browser registry 只能移除未知或未授權 route，不能自行增加權限。
- MKA action 仍套用 runtime capability／domain permission guards。
- owner、admin、sales、master、viewer 與 deployment-disabled manifest 情境皆
  有測試；Pack 關閉時 route 數量為零。
- 未發現 Critical／High correctness 或 authorization 問題。

## 驗證

- Frontend full regression：23 files／81 tests passed。
- ESLint：passed。
- TypeScript + Vite production build：passed。
- Backend Pack/bootstrap/authorization：39 tests passed。
- Browser gate：本次本機 `localhost:3001` 未啟動，無法重跑 authenticated
  browser E2E；不得將此項標示為本次通過。既有隔離環境 10/10 證據仍只代表
  前一版基線，部署至 staging 後需重跑。
- `git diff --check`：無 whitespace error，只有 Windows LF→CRLF 提示。
