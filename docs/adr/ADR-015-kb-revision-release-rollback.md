# ADR-015：知識庫版本、發布與回滾

- 狀態：Accepted
- 日期：2026-08-25

## 決策

`KnowledgeBaseRevisionDocument` 是不可變 membership，精確指向 `DocumentVersion` 與 document revision。chunks 與 lexical projection 均保存 document revision；指定 KB revision 的查詢必須在排序前綁定精確版本。

生命週期為 candidate → shadow → active → retired。瀏覽器不能宣告 gate PASS；發布只讀取伺服器產生、且同時綁定 revision id 與 manifest hash 的證據。回滾切換已驗收 revision，不在 active namespace 原地重建。

## 後果

重建索引不得刪除歷史 revision chunks。撤權／tombstone 的來源即使存在歷史向量也不得重新出現。
