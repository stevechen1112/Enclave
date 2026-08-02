# ADR-005：單一主索引與可選 Federated Retrieval

**狀態**：已接受
**日期**：2026-07-31
**決策者**：Enclave 技術團隊

---

## 背景

整合 RAGFlow、PipesHub、WeKnora 後，理論上可同時查詢多個向量索引：
- Enclave pgvector（自有）
- RAGFlow Elasticsearch/Infinity
- PipesHub Qdrant
- WeKnora pgvector/Neo4j

需要決定預設檢索策略。

## 決策

**GA 初期以 Enclave pgvector 為單一主索引。其他檢索能力僅在經評測證明有顯著增益後，以可選 specialist retrieval 啟用。**

### 預設路徑

```text
Query → Enclave pgvector (hybrid: semantic + BM25 + RRF)
      → Rerank (Voyage/local)
      → Context assembly
      → Single answer generation
```

### 可選 Specialist Retrieval（需評測閘門）

- RAGFlow specialist：僅對特定複雜文件 KB 啟用
- WeKnora Wiki/Graph：作為輔助召回（非替代主索引）
- PipesHub graph/context：作為外部企業脈絡召回

## 理由

1. **避免三份索引的成本**：三份向量索引意味著三倍的儲存、embedding 計算、同步維護。
2. **避免答案拼接**：多引擎各自生成答案再拼接會導致引用混亂、矛盾答案。
3. **評測驅動**：只有經 Hit@K/MRR/citation precision 評測證明增益 > 延遲/成本代價，才加入線上路徑。
4. **降級簡單**：單一主索引故障時降級路徑明確。

## 約束

- 禁止在沒有評測時同時查三份向量索引。
- 禁止讓三個下游各自生成答案後再拼接。
- 每個新 retrieval provider 上線前必須通過評測閘門（§8.4）。

## 後果

- 需要維護統一的評測框架與 baseline。
- RAGFlow/PipesHub/WeKnora 的檢索能力在初期不會被充分利用（直到評測通過）。
- 若日後評測證明多引擎顯著優於單一索引，需另開 ADR 調整策略。
