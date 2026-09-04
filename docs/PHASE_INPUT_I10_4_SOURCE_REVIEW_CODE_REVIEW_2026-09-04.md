# Input I10-4 來源層級人工確認 Code Review

日期：2026-09-04
狀態：`PASS（程式與本機回歸）／待正式資料複測`

## 結論

人工確認已由「逐筆清理所有技術 artifact」調整成「先確認一個來源的原始內容，再處理少數例外」。逐字稿、OCR、表格與整合原文可在同一交易中以來源為單位核准或退回；程序、規則推論、設備狀態與高風險內容保留在例外佇列。`speaker_turn`、`video_scene`、`timeline_alignment`、`sop_conflict_report` 不再是一般人工待辦。

## 權責規則

- 來源建立者可確認低風險、具證據的原文，讓兩人公司能完成基本發布閉環。
- 高風險或非逐字原文推論仍執行職責分離，建立者不能自行核准。
- 低信心原文需明確勾選確認；缺 ACL、缺 evidence 或政策失效一律 fail closed。
- 來源層級操作採單一交易，任一項失敗即全部 rollback，避免半批發布。

## Review 發現與修正

1. 技術結構原本會被計入待確認數量，造成 122 筆工作量膨脹；現已從佇列與 readiness 計數排除。
2. 原分組只有視覺效果，沒有真正的來源級 API；現新增 tenant-scoped source decision endpoint 與前端操作。
3. 建立者原本連逐字稿都被擋；現只對推論與高風險內容執行 separation-of-duty。
4. 整合原文 artifact 原本可能沒有 EvidenceSpan；投影器現替父 artifact 與子 chunk 建立同一套可稽核 evidence。
5. 即使同來源尚有高風險例外，已核准的原文仍可形成 active Knowledge Unit；UI 會清楚告知尚餘例外，不把兩者混成一個狀態。

## 驗證

- `tests/test_review_workspace.py`：3 passed，含 SQLite 交易整合、原文發布、推論留待確認、時間碼與 Knowledge Unit metadata。
- `frontend/src/pages/ReviewQueuePage.test.tsx`：5 passed，含來源級確認互動。
- Frontend TypeScript 與 ESLint：PASS。

Critical／High 未處理 code finding：0。正式五筆來源仍需在部署後以兩位 Owner 實際跑一次。
