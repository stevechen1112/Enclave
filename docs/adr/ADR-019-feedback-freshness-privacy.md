# ADR-019：回饋、保鮮、隱私與持續品質

- 狀態：Accepted
- 日期：2026-08-25

## 決策

沿用 `chat_feedbacks`，增加 owner、狀態與處理歷史；使用者回饋只建立 review 工作，不直接修改答案或提高來源權威。既有 KnowledgeGap 承擔缺口聚合；KnowledgeFreshnessState 保存複查、同步與過期狀態。

回饋分類固定為錯對象、數字、版本、來源、不完整、看不懂、應拒未拒、誤拒、權限與其他。正式 trace 保存前遮罩敏感資料，依租戶 retention 與角色授權存取。

## 後果

所有修復重新進 candidate 與發布 gates，禁止在線上答案層貼固定答案。
