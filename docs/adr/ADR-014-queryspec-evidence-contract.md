# ADR-014：QuerySpec 與 EvidenceContract

- 狀態：Accepted
- 日期：2026-08-25

## 決策

所有企業問答先投影為通用 `QuerySpec`，再建立含型別、實體、時點、範圍及必要性的 `AnswerSlot`。答案只能取用通過 ACL、revision、實體與型別檢查的 Evidence；缺必要欄位時只能 partial 或 abstain。

核心不得出現人資或特定客戶規則。垂直規則由 knowledge pack 實作標準介面。LLM 可解析意圖與組句，不得補造 slot 值。

## 後果

Evidence coverage 是放行條件，不再以相似度作為「可回答」的替代指標。回歸測試必須涵蓋錯實體、錯版本、缺欄與權限拒絕。
