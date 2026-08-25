# Enclave 通用企業知識庫全面提升計畫

**文件版本**：1.1  
**建立日期**：2026-08-24  
**最近審查**：2026-08-25  
**狀態**：核心實作與第二輪 code review 已完成；正式發布證據仍依第 12 節維持 NO-GO  
**定位**：跨產業、跨文件型態、跨企業流程的通用企業知識庫  
**適用範圍**：文件匯入、知識治理、檢索、AI 問答、現場 know-how、權限、評測、發布、瀏覽器驗收與正式環境營運

## 0. 執行摘要

Enclave 已具備 Catalog＋Chunk＋Compiled 多粒度檢索、QueryPlan、FusionPolicy、OCR 交付閘門、引用、來源驗證、權限與 know-how 草稿隔離等重要底座；但若要符合「普遍各領域企業知識庫」的定位，品質標準不能只停在「找到相關片段並附來源」。

全面提升後，每個答案都必須同時證明：

1. 使用了正確租戶、知識庫、文件、版本與權限範圍。
2. 找到的是正確客戶、設備、料號、工單、人員、專案或其他企業實體。
3. 金額、日期、數量、單位與狀態來自同一筆可驗證紀錄，不跨列拼接。
4. 使用者要求的欄位、項目、比較對象與流程分支已完整回答。
5. 每個事實都能追溯到原始頁面、段落、表格列或核准 know-how。
6. 文件不足、互相衝突或已過期時，系統能明確說明缺口，不猜測。
7. 新產業與新客戶不需要修改產品程式、寫死題目或加入客戶名稱特例。
8. 平台通用能力必須通過跨領域密封盲測；每個正式客戶的實際知識庫另做 corpus acceptance、無寫入 Shadow 與瀏覽器驗收，不以客戶驗收冒充平台泛化證據。

本計畫不是再增加一個檢索模型，也不是把其他垂直產品的規則搬進 Enclave；它要建立一套領域中立、可擴充、可稽核、可回滾的企業知識執行層。

---

## 1. 產品標準與完成定義

### 1.1 北極星標準

> 任意企業放入一批 Enclave 從未見過的文件後，系統能先判斷哪些內容可用、哪些內容不足，再對每個答案證明實體、欄位、版本、權限、完整性與來源；無法回答時，精確指出缺少什麼。

### 1.2 「通用」的硬性定義

下列條件必須同時成立，才能宣稱具備通用企業知識庫能力：

- 核心產品程式不得包含評測題號、完整題句、特定客戶答案或為單一文件建立的固定答案。
- 產業語彙只能存在於可設定的 ontology、schema、詞典或知識包，不得散落在核心流程的 `if/elif`。
- 未安裝任何產業知識包時，通用文件、表格、流程與版本能力仍須可運作。
- 新增產業知識包只可提升語意映射，不得繞過證據、權限、版本與發布閘門。
- 系統成功條件以未見資料、未見問法與正式使用流程衡量，不以已修題庫刷滿分衡量。

### 1.3 零容忍錯誤

以下任一情況皆直接判定 NO-GO，不以總分平均稀釋：

- 跨租戶、跨角色或跨部門洩漏。
- 引用已撤權、已刪除、非 active revision 或不可見文件。
- 答錯客戶、設備、料號、工單、專案、人員或其他實體。
- 把不同列、不同版本或不同文件的數值無痕拼成同一筆事實。
- 捏造金額、日期、數量、規格、程序步驟或核准狀態。
- 把草稿訪談、未核准 know-how 或 AI 彙整當成正式 SOP。
- 指定文件查詢時偷偷以其他文件補答，卻未告知使用者。
- 瀏覽器顯示的答案與來源卡不一致。

---

## 2. 現況基線與宣稱邊界

### 2.1 已有強項與限制

- OCR／掃描文件不得假完成的交付不變量；這證明交付狀態誠實，不代表正式環境已具備高品質掃描支援。
- Catalog、Chunk、Compiled 三種知識粒度。
- QueryPlan 與多步檢索編排。
- FusionPolicy 的來源權威、引用性與內部文件優先規則。
- 主文件、Wiki／compiled knowledge、外部 connector 的邊界。
- 引用、trace、source verifier 與 shadow／enforce 介面。
- know-how 訪談、草稿、核准與注入邊界的產品方向。
- Blind Z3／Z4 保留首次凍結分數，不以修正後成績覆蓋泛化證據。

目前正式能力圖仍將掃描 PDF／圖片列為弱、真實客戶 DOCX／XLSX／混排 PDF 列為未驗證；因此 K1 必須同時驗證「不假完成」與「內容真的可用」。

### 2.2 已知品質基線

| 基線 | 結果 | 正確解讀 |
|---|---:|---|
| 主集 | 128／128 | 回歸底線，不是未知資料泛化證明 |
| 對抗集 | 8／8 | 可保留為發布哨兵 |
| Blind Z3 | 67 PASS／3 FAIL／15 REVIEW，共 85 題 | 一次凍結、約 78.8% strict pass |
| Blind Z4 | 39 PASS／5 FAIL／6 REVIEW，共 50 題 | 全新 40 檔、78% strict pass；拒答 6／6 |

Z3／Z4 顯示目前最主要缺口是：

- 報價、表格與金額證據已存在，但答案漏掉關鍵值。
- 短客戶名或檔名 scope 召回不穩。
- 跨文件比較與完整列舉只回答部分項目。
- 來源驗證可以檢查「說出的話」，但不能完整檢查「應回答卻漏掉的欄位」。

### 2.3 正式環境知識基線

以下只代表 2026-08-24 唯讀快照，不得寫成永久驗收母數：

- 文件 24 筆：completed 21、deleted 2、failed 1。
- Document chunks 132。
- `knowledge_bases` 目前為 0；正式文件主要沿用租戶級檢索，而非已啟用的命名知識庫版本流程。
- know-how cards 2，皆為 draft；approved 0。
- retrieval traces 10。

K0 必須產生不可變 `production_corpus_manifest_id`，記錄當時 active 文件集合、版本、hash、ACL、KB scope 與統計。後續計畫一律引用 manifest ID，不再以「24 份」等會變動的數字作永久 GO 條件。

因此現階段不得宣稱：

- 本機 Z3／Z4 成績已代表正式站 24 份文件。
- 正式站已完成 candidate／active knowledge revision 的發布治理。
- 正式 know-how 已進入可引用知識層。
- source verification 已全面 enforce；目前程式預設仍為 `off`，必須經 shadow 誤判率驗證後才可受控啟用。

### 2.4 從 AIHR 比較研究採用與不採用的部分

採用：

- 依問題建立必答欄位、型別與最少值數的 EvidenceContract。
- 結構化資料的同列身分綁定、精確計算與程序專屬 resolver。
- active／candidate revision、租戶 allowlist、rollout 0 與可回滾發布。
- 不建立對話資料的正式環境 Shadow、前後 digest 與最終映像一致性。
- 真實瀏覽器多輪、來源卡展開及失敗後精準清理。
- 首次盲測成績永久保留，不將修正後回歸冒充新盲測。

不採用：

- 人資詞彙、特休／加班／資遣等垂直規則直接進 Enclave 核心。
- 以大量領域 `if/elif` 取代可設定 schema、ontology 與 resolver framework。
- 把已反覆修過的 220 題 Shadow 成績視為全新泛化證據。
- 每次小改動都套用同等重量的發布儀式；Enclave 採風險分級，但零容忍項目永不降級。

### 2.5 既有能力處置原則

施工前先建立 `Existing Capability Disposition Matrix`，每項只能標為沿用、擴充、遷移、淘汰或新增；不得未盤點就建立第二套模型。

| 現有能力 | 目前位置 | 1.1 處置 |
|---|---|---|
| KnowledgeBase／KnowledgeBaseRevision | `app/models/knowledge_base.py` | 擴充；補不可變 revision membership 與 runtime scope，不另建同名模型 |
| DocumentVersion | `app/models/kb_maintenance.py` | 擴充為不可變 DocumentRevision 語意，保留既有歷史資料 |
| KnowledgeGap | `app/models/kb_maintenance.py` | 沿用並擴充分類、owner、revision linkage；禁止建立第二張 gap 表 |
| ReviewItem | `app/models/review_item.py` | 沿用匯入審核；知識品質回饋若共用需加 item type，不混淆檔案審核狀態機 |
| KB health／backup／integrity API | `app/api/v1/endpoints/kb_maintenance.py` | 沿用並接上 revision、readiness 與 rollback 證據 |
| KnowhowCard／capture／lineage／reminder | `app/models/mka.py` | 沿用並補 authority、review scope 與 KnowledgeUnit projection |
| `structured_answers.py` | `app/services/structured_answers.py` | 遷移後淘汰核心直連；暫置 HR compatibility pack |
| QueryPlan | `app/services/query_plan.py` | 擴充為 QuerySpec；不建立另一條平行 query router |
| SourceVerifier | `app/services/source_verifier.py` | 擴充 deterministic validators、契約與模式化 SLO |
| CitationBuilder | `app/gateway/citation.py` | 修復 revision determinism；維持唯一 citation builder |

`KB-BL-01` 必須保存這份矩陣及實際引用關係；任何「新增」若與現有模型重疊，code review 直接阻擋。

---

## 3. 設計原則

### P1：證據足夠才回答

相似度高只代表可能相關，不代表足以回答。放行答案前必須檢查實體、欄位、範圍、版本、權威與完整性。

### P2：結構化資料優先於自由生成

表格、表單、清單、系統紀錄、計算與精確欄位優先走 deterministic／structured resolver；LLM 只負責理解問法與組織已驗證結果。

### P3：部分證據只能產生部分答案

若五個必答欄位只找到三個，系統只能回答三個並列出缺少兩個，不得生成看似完整的句子。

### P4：範圍必須可見

答案需保留 tenant、KB、revision、document、page／row、ACL、時間點與資料來源範圍；使用者指定範圍時不得靜默擴張。

### P5：權威是情境矩陣，不是固定排名

正式 SOP、ERP／MES 紀錄、核准 know-how、外部法規、客戶規格與 compiled summary 的權威性取決於問題情境；衝突時呈現差異與適用範圍，不自動猜誰取代誰。

### P6：發布、啟用、資料就緒與驗收是四件事

程式存在不等於旗標已開；旗標已開不等於資料可用；資料可用不等於客戶已經驗收。

### P7：評測不得污染泛化證據

sealed holdout 揭露後即轉為 regression。重大修正後必須建立新的 holdout，不得重跑同一批後宣稱是新盲測。

### P8：失敗應可行動

拒答或部分回答需指出缺少的文件、欄位、版本、適用範圍或使用者條件，並提供下一步。

### P9：規模、成本與部署型態是產品契約

通用企業知識庫不能只在數百 chunks 的 demo 庫成立。檢索、索引、Shadow、備份與回滾必須按 Lite／Team／Business／Enterprise 或實際部署 profile 定義容量、併發、成本與降級行為。

### P10：高風險知識不得自動變成高風險動作

工安、設備操作、品質放行、化學品、法律、醫療或財務高風險問題需要 `risk_class`、核准來源與明確警示。知識回答不得繞過既有 HITL／approval／write guardrail 直接操作 ERP、MES、設備或正式表單。

---

## 4. 目標架構

```text
來源文件／系統／錄音
  → 安全與權限掃描
  → 解析、OCR、表格、版面、語音轉錄
  → Document Profile + Structure Map + Quality Report
  → Canonical Knowledge Units
       ├─ catalog/document
       ├─ narrative chunk
       ├─ table/row/field
       ├─ form/record
       ├─ procedure/phase/branch
       ├─ entity/relation
       ├─ approved know-how
       └─ compiled summary/wiki
  → Candidate KB Revision
  → 資料就緒閘門＋回歸＋密封盲測
  → Active KB Revision

使用者問題
  → QuerySpec
  → RetrievalPlan
  → 多路檢索與 scope enforcement
  → Evidence Bundle
  → Evidence Contract／Coverage Matrix
  → Answer Decision
       ├─ Tier 0 deterministic
       ├─ Tier 1 structured/procedure
       ├─ Tier 2 source-grounded
       └─ Tier 3 partial/clarify/abstain
  → Claim、數值、實體、版本、完整性後驗證
  → 回答＋來源＋缺口＋trace
```

### 4.1 Canonical Knowledge Unit

所有索引、compiled projection 與回答證據應能投影為共同結構：

```text
KnowledgeUnit
  tenant_id
  knowledge_base_id
  kb_revision_id
  document_id
  document_revision
  unit_id
  unit_type: document | chunk | row | field | form | procedure | knowhow | compiled
  authority_class
  effective_from / effective_to
  acl_snapshot / policy_revision
  entity_ids[]
  parent_unit_id
  page / section / bbox / worksheet / row_id / field_name
  content
  content_hash
  quality_state
  parser_version / chunker_version / embedding_version
  ontology_version / index_schema_version
  source_refs[]
```

檔名只供顯示，不得作為唯一身分。文件、版本、列與欄位必須有穩定 ID。

### 4.2 版本語意與不可變 membership

五種版本不可混為同一欄位：

```text
DocumentRevision
  一份原始內容的不可變版本

KnowledgeBaseRevision
  某一時間點可見的 DocumentRevision 集合與 PolicySnapshot

KnowledgeBaseRevisionDocument
  KB revision 與 document revision 的不可變 membership

IndexArtifactRevision
  parser／chunker／embedding／BM25／reranker／compiled projection 的產物版本

RuntimeRelease
  image、model、prompt、flags 與 KB revision 的可部署組合
```

`manifest_hash` 只作完整性校驗，不能取代 membership 資料。回答引用必須指向實際 `DocumentRevision`；opaque 外部版本保存原始字串或固定 SHA-256，不得使用跨程序不穩定的語言 runtime hash。

### 4.3 QuerySpec

擴充既有 `QueryPlan`，建立領域中立、可追蹤的問題規格：

```text
QuerySpec
  operation: lookup | list | aggregate | compare | explain | procedure | summarize | verify
  target_types[]
  entities[]
  requested_slots[]
  operators[]
  temporal_scope
  document_scope
  knowledge_base_scope
  authority_constraints[]
  role_and_acl_scope
  expected_cardinality
  completeness_mode: exact | exhaustive | best_effort
  ambiguity[]
  risk_class: normal | sensitive | safety_critical
  confidence
```

QuerySpec 必須保留原始問題中的人名、代碼、數字、日期、否定詞與比較對象。多輪補全不得遺失原句資訊。

### 4.4 Evidence Contract

每個 `requested_slot` 建立獨立可驗證要求：

```text
AnswerSlot
  slot_id
  label
  value_type
  required
  minimum_values
  entity_binding
  source_scope
  authority_requirement
  temporal_requirement
  allowed_derivation
```

回答前建立 Coverage Matrix：

| Slot | 是否找到 | 實體一致 | 版本有效 | 來源足夠 | 值數足夠 | 結果 |
|---|---|---|---|---|---|---|
| 單價 | 是 | 是 | 是 | 是 | 1/1 | PASS |
| 交期 | 否 | — | — | — | 0/1 | MISSING |

### 4.5 Evidence Bundle

每個證據必須包含穩定 provenance：

- 文件與 revision ID。
- chunk、row 或 field ID。
- 頁碼、bbox、section、worksheet 與 row number（適用時）。
- 原文 quote。
- authority class。
- 可見性與 ACL 驗證結果。
- 實體綁定依據。
- 是否為原始資料、核准知識或 compiled projection。

### 4.6 Answer Decision

| Tier | 適用 | 規則 |
|---|---|---|
| Tier 0 | 計算、精確紀錄、狀態、金額、數量 | 必須 deterministic 且通過 row/entity binding |
| Tier 1 | 表格多欄、表單、程序、條款 | 使用專屬 resolver；不足可降級 Tier 2 或 partial |
| Tier 2 | 一般制度、手冊、報告、說明 | 僅使用 verified source-grounded facts |
| Tier 3 | 缺資料、範圍不明、衝突未解 | 澄清、部分回答或拒答；說明缺口 |

---

## 5. 十三條工作流

## WS-0：基線凍結與變更控制

### 目標

在改造前建立可重現的原始碼、正式映像、正式資料與評測基線，避免在目前大量未提交變更上失去版本證據。

### 工作

- 保存目前 commit、dirty file manifest、部署檔案 manifest 與正式 image digest。
- 建立正式環境唯讀基線：documents、chunks、KB、revisions、know-how、traces、users、ACL 與 digest。
- 建立 Existing Capability Disposition Matrix，確認沿用、擴充、遷移、淘汰與新增責任。
- 凍結主集、Z3、Z4、對抗集與所有 debug 集的用途分類。
- 建立測試資料與正式資料的清楚 tenant／KB 邊界。
- 將 `structured_answers.py` 及 ChatOrchestrator 中的人資規則列為領域中立化技術債：先凍結 regression，再移到 HR compatibility pack，通用 resolver 達 parity 後才移除核心直連。
- 修復 CitationBuilder 對 opaque revision 使用 runtime `hash()` 的不穩定行為，新增跨程序 revision stability gate。
- 盤點核心程式中的題號、客戶名、完整題句與垂直制度規則；註解可保留歷史理由，但執行分支不得依賴這些值。
- 任何施工先建立獨立分支與精確部署清單，不直接打包整個 dirty workspace。

### 出口閘門 `KB-BL-01`

- 原始碼、映像、資料、模型、prompt、旗標與題庫版本皆可追溯。
- 現有能力處置矩陣完成，0 個未說明的重複模型或重複主幹。
- opaque citation revision 跨程序、跨容器結果一致。
- HR compatibility 路徑已有明確 owner、feature flag、回歸集與退場條件。
- Z3／Z4 首次成績不可被覆蓋。
- 正式資料基線可由腳本重現且沒有敏感內容寫入 artifact。

## WS-1：匯入品質與知識就緒度

### 目標

從「文件 completed」提升為「文件適合哪些問題、哪些能力尚不可用」。

### 工作

- 每份文件產生 `DocumentProfile`：文件型態、頁數、OCR、語言、表格、流程、欄位、圖片、品質、解析警告。
- 建立格式能力矩陣，明列 supported／limited／experimental／unsupported：文字 PDF、掃描 PDF、DOCX、XLSX、PPTX、圖片、手寫、表單、流程圖、圖表、CAD／工程圖與錄音。
- 建立語言能力矩陣，至少分繁中、英文、中英混合、料號／縮寫與其他語言；未驗證語言不得宣稱支援。
- 建立 `StructureMap`：章節、頁面、表格、列欄、表單欄位、流程節點與父子關係。
- 建立能力 readiness：catalog、narrative、structured rows、procedure、entity、compiled、voice transcript。
- 對 OCR、表格、頁序、欄位斷裂、空頁與低信心區域給出可行動警告。
- completed 僅表示處理完成；`answer_ready` 必須按能力分別判定。
- connector 匯入保存來源 snapshot、external version、刪除／撤權狀態與同步水位；半次同步不得成為 active corpus。

### 出口閘門 `KB-INGEST-01`

- 0 筆掃描文件假完成。
- 100% active 文件具有 profile、manifest 與 capability state。
- 宣稱 structured-ready 的文件，依文件型態分層抽樣後 row/field 正確率達門檻；抽樣方法、母數與信賴區間依 §8.1。
- 解析失敗不得進 active revision。
- unsupported／limited 格式在 UI 與 API 都有誠實狀態，不靜默降級為一般文字成功。

## WS-2：知識庫版本、候選發布與回滾

### 目標

讓命名知識庫與 revision 真正成為正式問答執行單位。

### 工作

- 每個既有租戶建立 `Default Knowledge Base`，不複製文件內容。
- 將現有 `knowledge_base_id = NULL` 文件以 membership 遷移方式納入 R1。
- 支援 `draft → candidate → shadow → active → retired/rejected`。
- 新增不可變 `KnowledgeBaseRevisionDocument` membership，精確指向 `DocumentRevision`，而不是只保存文件現況或 manifest hash。
- active revision 僅能由通過資料與品質閘門的 candidate promote。
- revision manifest 保存文件集合、版本、權限 snapshot、索引 namespace、compiled artifact、parser／chunker／embedding／reranker／ontology／index schema 版本與 hash。
- rollback 同時切換檢索 scope、cache namespace、compiled projection 與顯示版本。
- 禁止 reindex 在 active revision 上原地清空再重建。

### 出口閘門 `KB-REV-01`

- active 與 candidate 可同時唯讀查詢且結果隔離。
- 任一歷史 revision 可僅依 membership 與 artifacts 重建，不讀取已被修改的 `documents` 現況冒充歷史。
- promote／rollback 不遺失來源與 ACL。
- 已取代、刪除或撤權文件不會由向量殘留重新出現。
- 正式環境可在 15 分鐘內回到上一個已驗收 revision。

## WS-3：QuerySpec 與領域中立答案契約

### 目標

讓系統知道使用者到底要求哪些可驗證內容。

### 工作

- 在既有 `QueryPlan` 上增加 entity、slot、operator、scope、cardinality、temporal 與 completeness。
- 建立金額、數量、日期、比率、單位、代碼、名稱、狀態、列表與比較的通用 value types。
- 產業 ontology／詞典以版本化 knowledge pack 載入；核心只讀標準介面，不直接引用特定產業答案。
- 支援「全部、分別、各自、合計、差異、最高／最低、截至某日、依某文件」等運算語意。
- 多輪改寫保留原句所有 named entity、數字、日期與否定詞；資訊遺失時退回原句。
- QuerySpec 低信心或缺關鍵實體時先澄清，不召回任意列。

### 出口閘門 `KB-QSPEC-01`

- 跨四個不同企業領域的新問法，QuerySpec 欄位人工正確率 ≥ 95%。
- 所有數字、日期、實體與否定詞 preservation = 100%。
- 核心程式 0 題號、0 客戶答案、0 完整題句特判。
- 未安裝任何垂直 knowledge pack 時，通用 QuerySpec 測試仍達門檻。

## WS-4：結構化紀錄、表格與計算引擎

### 目標

解決金額、報價、名單、設備台帳、料號、工單與多欄位查詢。

### 工作

- 建立 `StructuredRecordResolver`，使用可信 identity fields 而不是備註文字判定資料列。
- 保存 workbook、worksheet、table、row、field 的穩定 lineage。
- 同列多欄位查詢必須證明每個值屬於同一實體；跨工作表時需顯示口徑。
- 多實體查詢逐一 resolution，任何一個實體不足時不得用相似列代替。
- aggregate 使用 deterministic count／sum／min／max／filter；保存輸入列集合與計算式。
- 同名、別名、設備舊編號與客戶簡稱透過 entity registry 管理。
- EntityRegistry 必須 tenant-scoped；跨租戶同名與 alias 不得共享 resolution，除非引用明確核准的全域標準實體。
- 表格內容與正文不一致時呈現來源差異，不猜測。

### 出口閘門 `KB-ROW-01`

- 同列／同實體綁定測試 100% 通過。
- 錯人、錯客戶、錯設備、錯工單、跨列拼接 = 0。
- 金額、日期、數量與單位精確率 = 100%。
- aggregate 可重算且輸入列可追溯。

## WS-5：程序、流程與條件分支引擎

### 目標

讓 SOP、申請、維修、工安、品管與簽核流程不會只答到局部或串錯分支。

### 工作

- 將程序投影為 phase、step、actor、input、output、condition、exception、deadline 與 next step。
- 區分文件明載的步驟、由排序推得的關係與完全未知內容。
- 問「怎麼做」時檢查開始、主要步驟、分支、例外、完成條件與責任角色。
- 指定情境只走符合條件的分支，不能把不同流程拼接。
- 程序證據不足時輸出已知步驟與缺少部分，不自行補完。

### 出口閘門 `KB-PROC-01`

- 程序分支選擇正確率 ≥ 98%。
- 捏造步驟與錯誤責任角色 = 0。
- 問完整流程時，required phase coverage ≥ 95%。

## WS-6：證據編排、完整性與回答驗證

### 目標

把現有 source verifier 從「事後逐字驗證」提升為「回答前契約＋回答後驗證」。

### 工作

- 建立 EvidenceContract 與 Coverage Matrix。
- 建立 entity、numeric、date、unit、cardinality、scope、revision、authority validators。
- source verifier 由 `off → shadow → enforce` 逐租戶發布。
- shadow 階段量測錯殺、漏抓、成本、延遲與 provider failure。
- enforce 失敗時可重新生成一次；仍失敗則降級為已驗證部分答案或拒答。
- 回答 UI 顯示「已回答項目、尚缺項目、資料範圍與來源」。
- streaming 與 non-streaming 必須走相同驗證語意。

### 出口閘門 `KB-EVIDENCE-01`

- 未支持的事實進入使用者答案 = 0。
- required slot recall ≥ 95%；關鍵數值與實體 slot = 100%。
- source verifier shadow 誤殺率 < 2%，漏抓率 < 1%，才允許受控 enforce。
- verifier 失效不得靜默當作通過。

## WS-7：來源權威、衝突、時效與 know-how 治理

### 目標

正確處理正式文件、企業系統紀錄、外部規範、師傅經驗與 AI 彙整。

### 工作

- 建立可設定的 AuthorityPolicy，依問題情境決定來源優先序。
- 偵測同主題不同版本、適用廠區、客戶、產品或期間的衝突。
- 回答顯示版本、適用範圍與衝突；不可無痕融合。
- 長時間訪談逐字稿先進 provisional source，不直接進正式答案。
- know-how card 必須保存 speaker、時間、原始音訊／逐字稿位置、整理者、核准者、適用設備／場景、風險、到期／複查日。
- draft、rejected、expired know-how 不進一般回答；approved 才能依權限注入。
- 正式 SOP 與師傅經驗衝突時，兩者分層呈現並標示需管理者確認。
- safety-critical 回答只允許 approved、未過期且適用範圍吻合的來源；缺任一條件即 partial／abstain，並不得自動觸發設備、ERP／MES 寫入或品質放行。

### 出口閘門 `KB-AUTH-01`

- draft know-how 洩漏 = 0。
- 過期或被取代來源被當成現行標準 = 0。
- 衝突案例 100% 顯示來源、版本及適用範圍。
- 核准、撤回與到期後的檢索行為可立即驗證。
- safety-critical 回答轉成任何外部寫入前，HITL approval 與 write guardrail 100% 生效。

## WS-8：跨領域評測系統

### 目標

用真正未知的文件與問法證明通用性，不再只累積已修題庫。

### 題庫分層

| 分區 | 用途 | 是否可用來修程式 |
|---|---|---|
| Unit／contract | 模組正確性 | 可以 |
| Regression | 保護已修能力 | 可以閱讀 |
| Diagnostic | 找共同根因 | 可以閱讀 |
| Neighbor | 修正後防近鄰退步 | 可以閱讀 |
| Sealed holdout | 驗證未知問法與文件 | 開封前不可閱讀 |
| Production shadow | 驗證正式資料與部署路徑 | 不等同新盲測 |
| Human browser | 驗證完整使用流程 | 必須人工閱讀 |

### 跨領域最低語料

至少四個彼此獨立領域，每個領域使用未見企業資料：

1. 製造現場：SOP、設備、維修、異常、工安與師傅經驗。
2. 商務文件：報價、合約、客戶、交期、版本與跨檔比較。
3. 行政與結構資料：採購、名單、表單、費用、專案與精確欄位。
4. 技術與品質：規格書、檢驗報告、圖表、版本差異與故障排查。

每輪平台 sealed holdout 至少 200 個獨立案例、每領域至少 50 個；文件、客戶／組織名、內容 hash、近複本與題目語意不得與 regression 或上一輪 holdout 重疊。至少 20% 案例包含中英混合、縮寫、料號或跨語來源；未驗證語言另列，不混入通過宣稱。

客戶導入不要求重新證明平台泛化，而是建立 tenant corpus acceptance：依資料風險選 30–50 個代表案例，加上該租戶的 ACL、revision、無答案與瀏覽器流程；高風險客戶或大量客製 schema 可提高題數。Tenant acceptance 不計入平台 sealed holdout 分數。

### 必測能力

- 單檔事實、表格同列、多欄位與 aggregate。
- 多文件比較、完整列舉與版本衝突。
- 流程分支、角色、前置條件與例外。
- 多輪承接、主題切換、代名詞、否定修正與數字 preservation。
- 指定文件、不指定文件及指定時間點。
- 無答案、錯誤前提、弱相關詞與惡意 prompt injection。
- ACL、tenant、department、KB revision 與 draft know-how 隔離。
- retrieval Recall@K、scope recall、MRR／NDCG、同列候選召回與拒答所需反證召回。
- parser、chunker、embedding、reranker、ontology 或 model 變更的分層消融。

### 發布品質門檻

| 階段 | Strict pass | 各領域最低 | Critical error | 其他條件 |
|---|---:|---:|---:|---|
| 內部 alpha | ≥ 85% | ≥ 80% | 0 | 失敗已有分類與 owner |
| 對外 beta | ≥ 90% | ≥ 85% | 0 | required-slot coverage ≥ 95% |
| GA | ≥ 95% | ≥ 90% | 0 | 兩個連續新 holdout 達標 |

REVIEW 不算 strict pass。任何已揭露 holdout 修正後只能轉為 regression；必須另建新 holdout 才能更新泛化宣稱。

所有比率必須同時公布分子、分母、題型／領域分布與 95% Wilson 信賴區間。LLM judge 只能用於預分類；數字、實體、來源、scope 與 expected slots 優先使用 deterministic oracle。所有 FAIL／REVIEW 由未參與該題修復的人員覆核，並隨機覆核至少 10% 的機器 PASS；人工改判需保存理由與原始機器判定。

### 出口閘門 `KB-EVAL-01`

- 題庫、來源、GT、評分規則與 split 在執行前 hash 封存。
- 首次分數永久保存。
- 評分區分 assertion fail、environment blocked、skipped 與人工 review。
- 兩個連續、語料不重疊的 sealed holdout 達到目標階段門檻。
- Z5 作為 K0 後第一個全新 holdout，先驗證 2026-08-06 檢索修正；Z5 開封後永久轉為 regression，不充當第二輪 GA holdout。

## WS-9：正式環境 Shadow、發布與回滾

### 目標

證明最終映像在真實租戶資料與權限下可用，且不污染正式資料。

### 工作

- 建立不提供 conversation／message ID、不寫 cache／trace／usage 的 shadow runner。
- process-wide DB read-only barrier；所有預期寫入都要被拒絕並記錄。
- 執行前後比對正式資料 row counts、ID digests、KB revision、flags 與 ACL。
- 保存 commit、image digest、model、prompt、旗標、KB revision、題庫 hash 與結果 hash。
- 只允許 tenant allowlist、rollout 0 起步；逐步 5%／25%／100%。
- 每個階段有健康、錯誤率、拒答率、source validation、延遲與成本停止條件。
- 依 L0–L3 風險矩陣決定重跑範圍；L2／L3 必須使用最新最終映像重跑完整 tenant shadow，舊映像結果不能代替。

### 變更風險矩陣

| 等級 | 變更 | 最低發布要求 |
|---|---|---|
| L0 | 文件、純 UI 文案、無行為 refactor | static、受影響 unit、畫面 smoke；證明無 runtime 行為差異 |
| L1 | 單一 knowledge pack、isolated parser／resolver、非共用 UI | targeted＋neighbor＋tenant acceptance 抽測＋資料哨兵 |
| L2 | QuerySpec、retrieval、fusion、EvidenceContract、source verifier、model／prompt／embedding／reranker | 完整 regression、跨領域矩陣、正式 tenant shadow、瀏覽器多輪 |
| L3 | tenant／ACL、KB revision、DocumentRevision、刪除／撤權、migration、正式 ingestion、write／HITL | L2 全部＋隔離攻擊、完整資料基線、回滾演練與人工發布簽核 |

無論等級，零容忍錯誤一律 NO-GO；不得把實際會改變回答的變更申報為 L0。

### 出口閘門 `KB-SHADOW-01`

- 正式業務資料非預期寫入 = 0。
- 所有 delta 均能歸因。
- 最終部署映像與驗收映像完全一致。
- 回滾映像、備份、復原命令與復原 smoke 均已驗證。

## WS-10：知識治理 UI、問答 UI 與可觀測性

### 管理端「知識控制中心」

必須讓非工程管理者看懂：

- 目前正式使用哪個知識版本。
- 每份文件是可回答、部分可用、待處理、失敗、已取代或已過期。
- 哪些文件的 OCR、表格、程序或權限有問題。
- 哪些主題沒有資料、資料互相衝突或很久未複查。
- candidate 與 active revision 的差異。
- 評測、Shadow、發布、回滾與已知限制。

### 使用者問答介面

- 顯示回答範圍與資料時間點。
- 來源可展開到頁面、表格列或逐字稿位置。
- 部分答案清楚顯示已回答與缺少項目。
- 衝突答案並列來源與適用範圍。
- 允許回報「答錯對象／數字／版本／流程／來源／不完整」。
- 來源不可見時不得顯示可點擊但無法開啟的假卡片。

### 瀏覽器角色驗收

六道門是 demo persona，不等同授權角色。驗收必須涵蓋下列交叉維度：

```text
SystemRole（owner／admin／employee／viewer／superuser）
× JobRole（sales／equipment／supervisor／newcomer／其他租戶自訂）
× Department
× KB membership（reader／contributor／admin／owner／deny）
× Document／source-record ACL
```

目前六個 demo persona 作為代表場景逐一驗證：

- 業務：報價、客戶、合約與交期。
- 現場：設備、工單、SOP 與異常。
- 師傅：正式 SOP、核准 know-how 與訪談知識邊界。
- 新人：可理解的步驟、追問與權限限制。
- 唯讀：只能查詢，不可修改或核准。
- 擁有者／管理員：版本、權限、衝突、核准、發布與回滾。

每個 persona 必須走完整流程，不只確認選單存在；另以 pairwise 組合覆蓋上述授權維度，deny、viewer、跨部門與 KB membership 衝突必須全數顯式測試。

### 出口閘門 `KB-UX-01`

- 六 persona 所有代表知識流程通過，授權交叉矩陣 pairwise 覆蓋完成；所有 deny／跨租戶／跨部門負例 100% 通過。
- 來源展開、重新整理、返回、錯誤、空狀態、403／404 與手機版通過。
- 多輪主題切換與數字 preservation 通過。
- 管理員能在不看 log、不執行 SQL 的情況判斷資料是否可發布。

## WS-11：持續品質、知識保鮮與回饋閉環

### 目標

讓知識庫在正式使用後持續發現過期內容、覆蓋缺口與品質漂移，而不是只在上線前測一次。

### 工作

- 建立回饋分類：錯對象、錯數字、錯版本、錯來源、不完整、看不懂、應拒未拒、誤拒與權限問題。
- 使用者回饋只建立 review item，不得直接修改答案、提升來源權威或自動核准 know-how。
- 聚合未回答、低信心、反覆澄清與高頻查詢，形成 Knowledge Gap Queue。
- 對文件有效期、最後複查日、來源撤權、上游 connector 同步失敗與 entity alias 漂移告警。
- 每個 active revision 定期重跑 regression；模型、embedding、OCR、prompt、reranker 或權限政策變更時執行風險對應矩陣。
- 正式 trace 採樣前先做敏感資料遮罩；保存期間、可見角色與刪除規則需符合租戶政策。
- 缺口修正必須回到 candidate revision 與發布閘門，禁止直接在線上答案層貼補丁。
- 每季或重大架構變更後建立全新跨領域 sealed holdout，追蹤真正泛化趨勢。

### 出口閘門 `KB-OPS-01`

- 100% 使用者品質回饋有分類、owner、狀態與處理紀錄。
- 過期、撤權與 connector 失效資料不會繼續以現行來源回答。
- Knowledge Gap 修復均可追溯到 revision、測試與發布紀錄。
- 生產 trace 與評測 artifact 不含未授權的敏感原文。

## WS-12：規模、效能、成本與降級

### 目標

證明相同知識契約能在不同部署型態、資料量與併發下成立，避免只在數百 chunks 的 demo 環境可用。

### 工作

- 取代每次查詢載入全部 chunks 並重建 BM25 的路徑，建立持久化或可增量更新的 lexical index。
- 建立 1 千、1 萬、10 萬、100 萬 chunks 的容量階梯；若 Lite／地端 profile 不支援最高級距，需明列上限與升級方式。
- 量測單使用者、多使用者、批次 Shadow、同步 ingestion 與查詢併發時的 P50／P95／P99、錯誤率、記憶體與 CPU。
- 驗證 incremental ingest、document revoke、revision promote 與 rollback 不需全庫停機重建。
- 依 query tier 設 context、rerank、verifier、model token 與 provider 呼叫預算；超過預算時採可觀測降級，不靜默降低權限或證據標準。
- 建立 cost per answered query、cost per verified answer、shadow cost、index rebuild cost 與租戶配額儀表。
- provider timeout／rate limit／模型故障時，保留 scope、authority 與 abstention 規則；不得為追求可用性放寬安全不變量。

### 出口閘門 `KB-SCALE-01`

- 每個 deployment profile 有已驗證容量、併發、延遲、成本與儲存上限。
- 宣稱支援的最大級距下，retrieval 與 answer quality 不低於對應基線，tenant／ACL／revision 錯誤為 0。
- BM25 或其他 lexical index 不在每次查詢全量重建。
- L2／L3 發布前完成相符資料量的壓力、故障與降級測試。

---

## 6. 分期施工與依賴

| Phase | 主要內容 | 依賴 | 建議工期 | 完成出口 |
|---|---|---|---:|---|
| K0 | 基線凍結、能力處置、領域技術債、citation stability、Z5 | 無 | 1–2 週 | KB-BL-01 |
| K1 | Canonical unit、DocumentProfile、readiness | K0 | 2 週 | KB-INGEST-01 |
| K2 | KB revision、candidate／active、rollback | K0–K1 | 2 週 | KB-REV-01 |
| K3 | QuerySpec、AnswerSlot、EvidenceContract | K1 | 2–3 週 | KB-QSPEC-01 |
| K4 | StructuredRecord、aggregate、procedure | K3 | 3–4 週 | KB-ROW-01、KB-PROC-01 |
| K5 | Evidence orchestration、完整性、authority、know-how | K2–K4 | 2–3 週 | KB-EVIDENCE-01、KB-AUTH-01 |
| K6 | 跨領域題庫、sealed holdout、自動評分 | K3–K5 | 2–3 週，可與 K5 並行 | KB-EVAL-01 |
| K7 | 持久化 lexical index、容量、併發、成本與降級 | K2–K6 | 2–3 週 | KB-SCALE-01 |
| K8 | 知識治理 UI、來源 UI、六 persona 與授權矩陣 | K2–K7 | 2–3 週 | KB-UX-01 |
| K9 | 正式資料 Shadow、受控 rollout、回滾演練 | K0–K8 | 1–2 週 | KB-SHADOW-01 |
| K10 | 回饋、知識保鮮、漂移與定期再評測 | K6–K9 | 1–2 週建立；持續營運 | KB-OPS-01 |

第二輪審查後粗估：完整團隊約 16–24 週；若只有 1–2 名工程人員，應預留 24–36 週。以上含可合理並行工作但不含外部客戶等待，另保留至少 25% 風險緩衝。正式工期必須在 K0 完成 dirty worktree、既有能力處置、正式映像與資料基線後重新估算，不作為目前交付承諾。

### 不可顛倒的依賴

- 不先完成 K0，不得部署知識主幹改造。
- 不先完成 QuerySpec／EvidenceContract，不得只靠 prompt 宣稱完整性已提升。
- 不先完成 revision，不得在 active 正式索引原地重建。
- 不先完成 sealed holdout，不得用修正後 regression 宣稱泛化提升。
- 不先完成相符 deployment profile 的 KB-SCALE-01，不得以小型 demo 效能宣稱企業容量。
- 不先完成最終映像 Shadow，不得擴大正式 rollout。

---

## 7. 建議程式與資料交付物

名稱可在 ADR 階段調整，但責任不可省略：

### 核心模組

- 擴充 `app/services/query_plan.py`：QuerySpec 與 preservation。
- 新增 `app/services/evidence_contract.py`：AnswerSlot 與 coverage。
- 新增 `app/services/evidence_orchestrator.py`：Tier 決策。
- 新增通用 `app/services/structured_record_resolver.py`：row/entity binding；達 parity 後取代核心對 `structured_answers.py` 的直連。
- 新增 `app/services/procedure_resolver.py`：phase／branch completeness。
- 新增 `app/services/answer_completeness.py`：required slot 驗證。
- 擴充 `app/services/source_verifier.py`：claim、numeric、scope、revision。
- 新增 `app/services/kb_revision_runtime.py`：candidate／active scope。
- 新增 `app/services/authority_policy.py`：情境權威與衝突。
- 擴充既有 `KnowledgeGap` task／API；只有現有責任確實無法容納時，經 ADR 才新增 `knowledge_gap_service.py`。
- 新增或整合持久化 lexical index service，不得建立第二條繞過 RetrievalFacade 的檢索主幹。
- 將 HR compatibility pack 與其他垂直 knowledge pack 放在明確 plugin／pack 邊界，核心只依標準介面呼叫。

### 資料模型／migration

- 擴充既有 KnowledgeBaseRevision lifecycle 與 manifest hash。
- 不可變 DocumentRevision、KnowledgeBaseRevisionDocument membership、PolicySnapshot 與 RuntimeRelease。
- IndexArtifactRevision，保存 parser／chunker／embedding／lexical／reranker／ontology／compiled 產物版本。
- DocumentProfile／CapabilityReadiness。
- StructuredTable／StructuredRow／StructuredField lineage。
- ProcedureGraph／ProcedurePhase。
- EntityRegistry／EntityAlias。
- EvaluationRun／EvaluationCaseResult／HumanReview。
- KnowledgeRelease／RollbackPoint。
- 擴充既有 KnowledgeGap；KnowledgeFreshnessState 及品質 review item 是否沿用 ReviewItem，由 ADR-019 決定，禁止未評估就重建。

### 工具與 artifacts

- 正式資料唯讀 baseline 工具。
- KB revision diff／promote／rollback 工具。
- sealed question bank builder 與 hash manifest。
- non-persisting production shadow runner。
- browser acceptance evidence exporter。
- 統一 artifact schema，禁止大量無索引的臨時結果散落。

### 必要 ADR

- ADR-014：QuerySpec 與 EvidenceContract。
- ADR-015：命名知識庫 revision、promotion 與 rollback。
- ADR-016：Structured record identity／row binding。
- ADR-017：來源權威、衝突與 know-how lifecycle。
- ADR-018：跨領域盲測與正式 Shadow 發布閘門。
- ADR-019：知識回饋、保鮮、隱私與持續品質。
- ADR-020：領域 knowledge pack／compatibility layer 與核心去耦。
- ADR-021：持久化 lexical index、容量 profile、成本與故障降級。

---

## 8. 測試與發布矩陣

### 8.1 量測方法

- 所有品質門檻的統計單位是獨立 evaluation case；多輪案例另報 case 與 turn，不可把 turns 當更多獨立案例灌大母數。
- 報告必含分子、分母、題型、領域、格式、語言、風險層級、模型／prompt／KB revision 與 95% Wilson 信賴區間。
- structured-ready row／field 抽查採文件型態分層抽樣；每種宣稱格式至少 30 rows 且至少涵蓋 5 份文件，母數不足則全查。
- source verifier 誤殺率以「正確且完整答案被攔」為分子；漏抓率以「含 unsupported critical claim 卻放行」為分子。兩者至少各有 200 個標註案例後才可作 enforce 決策。
- 拒答分別報 precision 與 recall，不用單一「correct abstention」混合兩種錯誤。
- retrieval 分別報 Recall@K、scope recall、MRR／NDCG、critical evidence recall 與 row identity recall；end-to-end PASS 不能取代檢索診斷指標。
- LLM judge 的 provider、model、temperature、schema failure 與 resume 行為必須鎖定；它只能預分類，不得覆蓋 deterministic oracle 或人工原始判定。

### 8.2 固定矩陣

每次知識主幹變更至少執行：

| 層級 | 必跑內容 |
|---|---|
| Static | compile、lint、migration graph、diff check、禁止題號／題句掃描 |
| Unit | QuerySpec、slot、row binding、procedure、authority、validators |
| Integration | PostgreSQL、pgvector、cache、revision、ACL、deleted-vector sentinel |
| Regression | 主集、Z3、Z4、既有對抗集與修洞 neighbor |
| Cross-domain | 四領域 A／B／C／D 固定矩陣 |
| Blind | 全新 corpus＋全新 sealed questions，首次結果凍結 |
| Shadow | 正式 tenant、active revision、process-wide read-only |
| Browser | 六 demo persona、授權交叉矩陣、多輪、來源卡、管理、手機與錯誤流程 |
| Operations | image、flags、health、metrics、backup、rollback |
| Capacity | 宣稱 deployment profile 的資料量、併發、成本、故障與降級 |

A／B／C／D 定義為：A 單檔與結構化精確題；B 多文件、程序、比較與完整性；C 無答案、錯誤前提、衝突與時效；D tenant／ACL／revision／prompt injection／高風險與多語控制。每批都需包含正例、反例與中性控制。

測試報告必須分開呈現：

- 真正 passed assertion。
- environment blocked。
- skipped。
- failed。
- human review。

不得把重疊測試相加成總通過數，也不得將人工裁定與 strict oracle 混為同一數字。

---

## 9. SLO 與營運指標

### 品質

- Critical factual／security errors：0。
- Required slot coverage：Beta ≥ 95%，GA ≥ 98%。
- Citation／claim support：≥ 99%，關鍵數字與實體 100%。
- Abstention precision ≥ 95%，abstention recall ≥ 95%，並分一般題與高風險題報告。
- 多輪重複提問一致性：≥ 95%。

### 效能

- Structured lookup P95 ≤ 3 秒。
- `off／shadow` 一般問答 first token P95 ≤ 3 秒；`enforce` 目前會緩衝完整答案，不套用此 TTFT，改量測 verified-answer latency。
- `off／shadow` 完整回答 P95 ≤ 12 秒；`enforce` verified answer P95 先以 ≤ 20 秒為 beta 目標，K7 實測後再收斂。若要保留 3 秒 TTFT，必須另設計 claim-safe staged streaming，不得先送出未驗證事實。
- Shadow／verifier 增加的 P95 延遲與成本必須獨立量測。
- SLO 依 deployment profile 與資料級距分開，不以小型 demo 數字代表 Enterprise。

### 營運

- 每次回答可追溯到 image、model、prompt、flags 與 KB revision。
- active revision rollback RTO ≤ 15 分鐘。
- 上述 15 分鐘只作 managed beta 目標；地端或大型 deployment profile 必須另訂並驗證 RTO／RPO。
- failed ingestion 與 stale knowledge 有告警及 owner。
- tenant／ACL／revision scope mismatch = 0。
- 每個 profile 有單題、每千題、每次 Shadow 與每次 index rebuild 的成本預算及告警。

---

## 10. 主要風險與控制

| 風險 | 控制方式 |
|---|---|
| 核心程式被產業規則塞滿 | 核心 schema 與 plugin／ontology 分離；靜態掃描與 code review |
| EvidenceContract 太嚴導致過度拒答 | shadow 量測、partial answer、分題型門檻 |
| EvidenceContract 太鬆導致漏欄位 | sealed multi-slot／exhaustive 題庫與 coverage matrix |
| 表格 OCR 或 header 錯造成跨列 | row lineage、identity fields、人工抽查、低信心不 promote |
| revision 遷移污染正式索引 | Default KB R1 snapshot、candidate shadow、精確 rollback |
| verifier 成本與延遲過高 | deterministic validators 優先、抽樣 shadow、模型分級 |
| 盲測被反覆修到失真 | 首次 immutable、揭露即 regression、新 corpus holdout |
| 正式測試污染客戶資料 | process-wide read-only、digest、精確 ID manifest |
| UI 只呈現技術欄位 | 以「可用／缺資料／衝突／待核准／可回復」的企業語言呈現 |
| 重建既有 KnowledgeGap／Review／know-how | K0 capability disposition；ADR 未通過不得新增平行表 |
| Citation revision 跨程序漂移 | 保存原始 revision 或固定 SHA-256；跨容器 stability gate |
| 小型 demo 效能冒充企業容量 | KB-SCALE-01、容量級距、併發、成本與故障測試 |
| 高風險回答被直接執行 | risk class、approved source、HITL 與 write guardrail |
| 支援格式宣稱過廣 | supported／limited／experimental／unsupported 能力矩陣 |

---

## 11. 人力與責任

建議最低配置：

| 角色 | 主要責任 |
|---|---|
| Knowledge／RAG backend | QuerySpec、retrieval、evidence、resolver |
| Data／ingestion engineer | OCR、表格、structure map、revision indexing |
| Backend／security | ACL、tenant、revision、release、audit |
| Frontend／UX | 知識控制中心、來源、partial／conflict UI |
| QA／eval | corpus、GT、sealed holdout、browser acceptance |
| DevOps | image、shadow、metrics、backup、rollback |
| Domain reviewer | 只審來源與 GT，不撰寫產品特判 |

同一人可兼任多項角色，但 sealed holdout 的出題／封存與修復實作者應盡量分離。

---

## 12. 對外測試前的最終 GO／NO-GO

### GO 必要條件

- `KB-BL-01`、`KB-INGEST-01`、`KB-REV-01`、`KB-QSPEC-01`、`KB-ROW-01`、`KB-PROC-01`、`KB-EVIDENCE-01`、`KB-AUTH-01`、`KB-EVAL-01`、`KB-SCALE-01`、`KB-UX-01`、`KB-SHADOW-01` 全部通過。
- KB-OPS-01 的回饋、過期與敏感資料治理已建立，不要求累積特定數量的正式回饋才可開測。
- 最新映像、正式 active revision 與正式 flags 已鎖定。
- 兩個連續新 sealed holdout 達對外 beta 門檻，critical error = 0。
- K0 凍結的 `production_corpus_manifest_id` 及其後續 active manifest 已建立覆蓋地圖、tenant acceptance 與 Shadow 證據；母數變動皆可解釋。
- 六 demo persona 的瀏覽器完整流程、手機操作及 SystemRole × JobRole × Department × KB membership × ACL 負例通過。
- source verification 至少在正式 tenant shadow 穩定；是否 enforce 有書面決策。
- 2 張 know-how draft 不得誤入一般回答；若尚無 approved card，UI 必須誠實顯示尚未核准。
- 有可實際執行的 rollback point 與已驗證復原 smoke。

### 直接 NO-GO

- 任何零容忍錯誤。
- 以 Z3／Z4 debug 或已揭露題重跑冒充新盲測。
- 最新 image 尚未完成 Shadow。
- 正式資料 delta 無法歸因。
- 只能靠改 prompt、關閉來源或客戶／題目特判通過。
- 管理員無法判斷目前使用哪個知識版本。
- opaque revision 跨程序不穩定，或回答無法指回精確 DocumentRevision／KBRevision。
- 只在數百 chunks 通過，卻未完成宣稱 deployment profile 的 KB-SCALE-01。

---

## 13. 第一個可執行 Sprint

在不改變正式問答行為的前提下，先完成：

1. `KB-BL-01`：凍結工作區、正式映像、`production_corpus_manifest_id` 與題庫用途。
2. 完成 Existing Capability Disposition Matrix，特別盤點 KnowledgeGap、ReviewItem、KB 維護、know-how 與 structured answers。
3. 修復 CitationBuilder opaque revision determinism，加入跨程序／跨容器測試。
4. 凍結 `structured_answers.py` 與 ChatOrchestrator HR 快速路徑 regression，定義 compatibility pack 與退場條件。
5. 在任何知識主幹行為修改前，執行並永久凍結 Z5 新 holdout，驗證 2026-08-06 檢索修正。
6. 為 K0 active corpus manifest 建立 DocumentProfile 與知識覆蓋地圖。
7. 建立 Default Knowledge Base R1、DocumentRevision 與 KnowledgeBaseRevisionDocument 遷移設計及 dry-run，不直接 commit 正式 DB。
8. 定義 QuerySpec、AnswerSlot、EvidenceRef、Coverage Matrix schema 與 ADR-014 草案。
9. 從 Z4 fail／review 抽象出金額、多欄位、跨檔完整性與短實體四組 contract tests。
10. 建立程式特判掃描器，禁止題號、完整題句與客戶固定答案進核心執行分支。
11. 建立正式知識庫 shadow runner 的 read-only 與 digest 契約骨架。

Sprint 出口是「基線與契約可審查」，不是提前宣稱品質已提升。

---

## 14. 與既有計畫的關係

| 既有文件 | 本計畫如何承接 |
|---|---|
| `FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN.md` | 保留 Catalog／Chunk／Fusion／OCR 底座；本計畫向答案完整性、revision 與發布延伸 |
| `VISION_POINT_A_TO_B.md` | 保留盲測與能力上限方法；本計畫提高為跨領域與正式租戶標準 |
| `DEVELOPMENT_PLAN_TRIPLE_INJECTION.md` | 沿用 canonical、projection、outbox 與 control plane，不建立平行真相 |
| `MANUFACTURING_KNOWLEDGE_ASSISTANT_ENGINEERING_PLAN.md` | 製造業作為第一個垂直驗證場景，不等同 Enclave 核心只服務製造業 |
| `CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md` | 新檢索或 compiled 能力仍須消融證明增量，不因存在就預設全開 |
| `ENCLAVE_2_0_TECHNICAL_DD.md` | 版本、引用、索引、權限與部署缺口必須納入 K0／K2 清理 |
| `PIPELINE_STRENGTH_MAP.md` | 掃描、真實格式、BM25 規模與 Z5 優先序作為 K0／K1／K7 現況證據 |

本計畫是 Enclave 通用知識庫的總體品質與發布主計畫；既有專項計畫提供底層證據，不再各自以局部 PASS 宣稱整體完成。

---

## 15. 最終產品宣稱

完成對外 beta 閘門後，可以宣稱：

- Enclave 可處理多種企業文件、表格、流程與核准 know-how。
- 回答受實體、欄位、版本、權限、完整性與來源約束。
- 新客戶資料會先經 readiness、盲測與 Shadow，再進正式 active revision。
- 文件不足或衝突時，系統會顯示缺口與適用範圍，不自行猜測。

在 GA 閘門前不得宣稱：

- 可保證回答任意企業、任意問題。
- 所有掃描件、圖面與表格都能百分之百自動理解。
- 已修過的題庫滿分等於未知文件泛化。
- 有來源就代表答案必然正確或完整。

---

## 16. 版本紀錄

| 版本 | 日期 | 摘要 |
|---|---|---|
| 1.0 | 2026-08-24 | 建立通用知識庫目標架構、十二工作流與發布門檻 |
| 1.1 | 2026-08-25 | 第二輪架構審查：加入既有能力處置、不可變 revision membership、HR compatibility 退場、citation stability、平台／租戶評測分離、統計方法、授權交叉矩陣、規模／成本／多語／高風險 HITL 與 L0–L3 發布矩陣 |
