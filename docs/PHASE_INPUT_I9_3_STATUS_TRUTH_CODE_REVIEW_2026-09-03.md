# Input I9-3 Code Review：狀態單一真相

日期：2026-09-03  
結論：PASS，可進入 I9-4

## 變更範圍

- 資產 API 新增 `answer_ready`、`lifecycle_status`、`pending_review_count` 與原因。
- 所有首頁數字改按來源資產計算，不再把衍生候選數當成來源數。
- `已可問答` 依實際 Ask serving mode 判定：authority enforce 模式要求正式 active membership；shadow 過渡模式要求 current completed revision、ready profile 與可檢索 chunk 同時成立。
- 狀態互斥且有優先序：失敗、處理中、已可問答、等待人工確認、需要處理、已收到。
- 人工確認佇列只顯示其 ingestion job 仍為 `review_required` 的衍生內容，避免已完成來源的殘留候選污染待辦。
- 首頁狀態卡可直接前往對應工作，並清楚區分「來源數」與「候選內容數」。

## Review 發現與修正

1. 原始設計僅以 active KB revision 判定，會與 production 的 authority shadow serving mode 不一致；已改為 serving-mode-aware，避免 UI 顯示不可用但 Ask 實際可用，或反之。
2. review artifact 計數最初可能包含舊 asset revision；已限制於每個來源的 current revision。
3. 首頁原本用 `asset.status == active OR job.status == ready`，會把卡住圖片誤算為可使用；已移除推測式算法。
4. 舊 API `processing_status=failed` 等篩選仍保留相容性；新增 canonical lifecycle 篩選供新版 UI 使用。

## 驗證證據

- `pytest -q tests/test_knowledge_assets.py tests/test_review_workspace.py tests/test_input_i9_asset_readiness.py`：11 passed。
- `vitest`：首頁與資產庫 4 passed。
- TypeScript `tsc -b`：通過。
- Vite production build：通過，3257 modules transformed。
- `python -m compileall`：通過。
- `git diff --check`：無 whitespace error。

## 剩餘風險

- PostgreSQL 路由／RLS 整合測試仍需於可用測試資料庫或部署前 staging 執行。
- I9-4 尚需把資產詳情的錯誤原因、自動重試語意與責任人完整白話化。
- I9-5 尚需把人工確認工作台由候選平面清單改為來源分組。
