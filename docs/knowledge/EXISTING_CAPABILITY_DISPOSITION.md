# Existing Capability Disposition Matrix

本文件是 `KB-BL-01` 的責任邊界。新增模型不得繞過下列既有主幹。

| 能力 | 既有主體 | 處置 | 唯一責任／退場條件 |
|---|---|---|---|
| 命名知識庫 | `KnowledgeBase` | 擴充 | 不建立第二套 KB；revision runtime 只操作此 aggregate |
| KB 版本 | `KnowledgeBaseRevision` | 擴充 | lifecycle、manifest、namespace 均保存在既有 revision |
| 文件版本 | `DocumentVersion` | 擴充語意 | 作不可變內容 snapshot；membership 必須指向它 |
| Revision membership | 無 | 新增 | `KnowledgeBaseRevisionDocument` 是唯一不可變 membership |
| 文件匯入 | `Document`／parse pipeline | 擴充 | `DocumentProfile` 描述能力，不取代 processing status |
| 文件產物 | `DocumentArtifact` | 擴充 | provider 原生 artifact；`IndexArtifactRevision` 只保存 revision 級 manifest |
| 查詢編排 | `QueryPlan` | 擴充 | QuerySpec 欄位直接加入，不另建平行 router |
| 結構化回答 | `structured_answers.py` | 遷移 | 僅能由 `hr_compatibility` flag 路徑使用；通用 resolver parity 後退場 |
| 來源驗證 | `SourceVerifier` | 擴充 | EvidenceContract 是回答前契約；verifier 是回答後驗證 |
| 引用 | `CitationBuilder` | 擴充 | 唯一 citation builder；opaque revision 固定 SHA-256 |
| know-how | `KnowhowCardModel` 等 | 擴充 | 不建立第二套卡片；只投影核准且有效內容 |
| 知識缺口 | `KnowledgeGap` | 擴充 | 不建立第二張 gap 表 |
| 匯入審查 | `ReviewItem` | 沿用 | 檔案審查狀態機不與回答品質回饋混用 |
| 檢索主幹 | `RetrievalFacade` | 擴充 | lexical／row／procedure 臂仍須經 Facade 與 FusionPolicy |

Owner：Knowledge/RAG backend。每次架構 review 必須檢查重複 aggregate、繞過 Facade、核心垂直規則與 active index 原地重建。

