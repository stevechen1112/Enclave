# ADR-002：Enclave Canonical Store 與 Projection 邊界

**狀態**：已接受
**日期**：2026-07-31
**決策者**：Enclave 技術團隊

---

## 背景

整合 RAGFlow、PipesHub、WeKnora 後，同一份文件會產生多份衍生資料：
- RAGFlow 解析結果（page/bbox/table structure）
- Enclave 自有的 chunk + pgvector embedding
- PipesHub 來源 ACL 快照
- WeKnora Wiki 頁面 + Graph 實體

需要明確定義哪些資料是權威（canonical），哪些是可重建投影（derived projection）。

## 決策

**採用 Canonical Store + Derived Projection 分離模型。**

### Canonical Store（Enclave PostgreSQL + Object Storage）

Enclave 為以下資料的唯一權威：
- 客戶、使用者、部門、角色、群組與政策
- KB、文件登錄、來源識別、保留政策與生命週期
- 有效權限（effective authorization decision）
- 公開 API、產品設定、授權與配額
- 最終引用、稽核、成本與使用記錄
- 原始檔案（immutable blob，以 content_hash 識別）

### Derived Projection（可重建）

以下資料為可重建投影，可從 Canonical Store 重新產生：
- 解析結果（page/bbox/table/reading-order）
- Chunk 與 Embedding
- Wiki 頁面
- Graph 實體與邊
- 下游專用索引

## 理由

1. **災難復原**：Canonical Store 備份即可保證完整還原；projection 可重建。
2. **授權一致性**：權限變更只需更新 Canonical Store 的 policy revision，projection 依 revision 收斂。
3. **下游替換**：更換解析/Wiki/Graph provider 時，只需重建對應 projection。
4. **稽核鏈**：所有回答的引用最終追溯到 Canonical Store 的文件 revision。

## 約束

- 原始檔案進入 Enclave object storage，使用不可變 `content_hash` 與版本識別。
- PipesHub 來源系統仍是外部內容與來源 ACL 的權威；Enclave 保存同步快照與 lineage。
- WeKnora Wiki 是衍生知識，不得取代原始來源與引用。
- 下游故障不得阻止 Enclave 立即拒絕已刪除或已撤權的資源。

## 後果

- 需要維護 `projection_status` 表追蹤每個 projection 的收斂狀態。
- 需要 reconciliation job 定期修復不一致的 projection。
- Embedding 重建對大型 KB 可能耗時數小時，需在備份策略中納入。
