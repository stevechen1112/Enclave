# ADR-021：持久化 lexical index、容量與降級

- 狀態：Accepted
- 日期：2026-08-25

## 決策

lexical index 以 PostgreSQL 持久化、隨 chunk 增量 upsert，token array 使用 GIN 產生有界候選集；查詢期間不得載入整個租戶語料重建 BM25。索引列綁定 tenant、document、document revision、chunk 與 content hash。

語意、lexical、reranker 或外部 provider 故障時，系統回報 partial／degraded，不把失效當成功。容量一律按 **chunks** 計數，避免用文件數冒充索引規模：Lite 驗證 1k／10k、Team 驗證 1k／10k／100k、Enterprise 驗證至 1M。每個 profile 必須在最低併發下量測 P50／P95／P99、錯誤率、hit@10、ACL/revision scope violation、CPU、記憶體、索引大小與基礎設施成本；操作者資源觀測需綁定同一 image digest 並附 attestation hash。

## 後果

candidate 的 projection 未完整覆蓋 membership chunks 時，KB-REV-01 不得通過。
