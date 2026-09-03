# KQ5 Code Review — Answer Plan、Renderer 與問答 UX

- 日期：2026-09-03
- Gate：`KQ-ANSWER-01`
- 結論：**PASS TO NEXT PHASE**

## Review 結論

KQ5 新增 domain-neutral `AnswerPlan`，只消費 canonical `EvidenceDecision.verified_claims`。Scalar、set、procedure、judgment、definition、comparison、formula 與 partial gap 都由 deterministic renderer 安全輸出；render text、claim IDs、plan hash 與 render hash 可重現及 diff。

Constrained paraphrase 必須聲明完整 verified claim IDs。`SourceVerifier` 會拒絕未知或遺漏 claim、未支持的數字／日期／代碼／entity，以及超出 reviewed scope 的宣告；任何失敗一律回退 deterministic renderer，不回傳未驗證草稿。未來的 Enforce 串流會直接輸出 verified render，或沿用既有 buffer-until-verified 防線，不會先吐出草稿。

Ask UI 已能顯示 complete、partial、insufficient context、absent、conflict 與 execution failure，並分開呈現適用範圍、已回答項目、缺少項目及衝突。Execution failure 明確標示為系統未完成，不會顯示成公司沒有資料。Evidence drawer 保留文件頁碼、section path、表格列、圖片區域、speaker、音訊時間碼、影片 frame／keyframe 與來源版本，所有操作支援鍵盤及無 hover。

## 驗證證據

- KQ0–KQ5、SourceVerifier、chat catalog、demo login：113 passed，0 failed。
- Frontend ChatPage 與 DecisionSummary：5 passed，0 failed。
- TypeScript project build：PASS。
- Vite production build：PASS。
- Ruff（KQ5 新增／修改核心）：PASS。
- Machine-readable report：`artifacts/knowledge/KQ5_GATE_REPORT.json`。

## Gate 判定

AnswerPlan 與輸出可 deterministic diff，invalid draft 不洩漏，sync／stream final output 與 claims 使用同一 render，UI 正確區分 evidence state 與 execution status。`KQ-ANSWER-01` 通過，允許開始 KQ6；正式 `KNOWLEDGE_DECISION_MODE` 仍為 `off`，本結論不構成 KQ7 Enforce 授權。
