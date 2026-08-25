# ADR-016：結構化資料列身分綁定

- 狀態：Accepted
- 日期：2026-08-25

## 決策

表格由 StructuredTable、StructuredRow、StructuredField 保存 worksheet、頁面、列號、bbox、原值、正規值與 hash。多欄回答必須來自同一個符合 identity 的 row；不得把不同客戶或不同列的欄位拼成一筆。

count、sum、min、max 等計算走 deterministic resolver，輸出輸入列 ID、輸入值與結果。無法唯一綁定時要求澄清或拒答。

## 後果

LLM 不負責精確算術及跨列配對。宣稱 structured-ready 的文件必須已有可抽查 rows，否則匯入 gate 失敗。
