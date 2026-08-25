# ADR-020：領域 Knowledge Pack 與核心去耦

- 狀態：Accepted
- 日期：2026-08-25

## 決策

核心只提供 QuerySpec、EvidenceContract、resolver、authority 與 citation 契約。人資、製造或其他產業規則以 knowledge pack 接入；既有 `structured_answers.py` 暫置 HR compatibility pack，預設關閉，達到通用 resolver parity 後移除核心直連。

## 後果

CI 靜態掃描禁止題號、完整測試問句、客戶固定答案及領域專用公式進核心。Pack 可以演進，但不得繞過 ACL、revision 與 EvidenceContract。
