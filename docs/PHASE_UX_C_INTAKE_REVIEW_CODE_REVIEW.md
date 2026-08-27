# Phase UX-C Multimodal Intake and Review Code Review

**日期：** 2026-08-27
**決策：** PASS，可進入 UX-D

## 範圍

- 統一 intake 支援受控格式的多檔選取與拖放。
- 每個檔案呈現預期處理能力、上傳進度、成功與失敗狀態。
- 多檔以逐筆 canonical API 建立，不宣稱具備後端不存在的原子批次。
- 部分失敗時保留成功結果，只重試未完成項目。
- 重新審視 Review Workspace 的 evidence、risk、confidence、SOP conflict 與
  publication contract 行為。

## Review 發現與修正

- 初版拖放只限制 input picker，拖入時仍可能接受未列出的格式；review 中
  改為 `react-dropzone` MIME／副檔名 accept contract，拒絕項目不進入佇列。
- 多檔共用自訂標題會造成來源難以識別；多檔模式強制沿用各自檔名。
- 已完成項目不會因失敗重試再次上傳。
- Review approval 仍 fail-closed：缺 evidence、未確認高風險／低信心或未解
  SOP conflict 時不可發布。
- 未發現 Critical／High correctness、authorization 或 traceability 問題。

## 驗證

- 定向 Vitest：3 files／6 tests passed。
- 新增多檔逐筆 canonical request 測試。
- ESLint：passed。
- TypeScript + Vite production build：passed。
