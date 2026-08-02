# Enclave 技術實力基準評測：8 專案交叉比較

**文件版本**：2026-07-30
**比較對象**：Enclave × RAGFlow × WeKnora × OpenKB × OpenDocuments × OpenRAG × PipesHub AI × OpenAI Knowledge Retrieval
**目的**：以開源知識庫專案為基準，評測 Enclave 核心技術能力的強弱項，為 Agent 產品開發優先序提供技術依據。

---

## 總覽矩陣

| 維度 | **Enclave** | RAGFlow | WeKnora | OpenKB | OpenDocuments | OpenRAG | PipesHub AI | OpenAI KR |
|---|---|---|---|---|---|---|---|---|
| **語言** | Python | Python+Go | Go+Python | Python | TypeScript | Python+TS | TS+Python | Python |
| **授權** | 私有 | Apache 2.0 | Apache 2.0 | MIT | AGPL 3.0 | Apache 2.0 | 私有 | MIT |
| **定位** | 企業地端全棧 | 開源 RAG 引擎 | 企業知識框架 | CLI 知識編譯 | 本地 RAG 工具箱 | RAG 平台 | 企業 AI 中台 | RAG 參考實作 |

---

## 一、文件解析能力

| 能力 | Enclave | RAGFlow | WeKnora | OpenKB | OpenDocuments | OpenRAG | PipesHub | OpenAI KR |
|---|---|---|---|---|---|---|---|---|
| 支援格式數 | **23** | 15+ | 12+ | 9 | 12 | 8+ | 12+ | 7 |
| OCR | ✅ pytesseract | ✅ PaddleOCR/Mistral | ✅ VLM OCR | ❌ (付費) | ✅ fallback | ✅ EasyOCR | ✅ Docling | ❌ |
| 表格結構識別 | ✅ | ✅ **10 種版面+5 種表格** | ✅ | ❌ | ✅ sheet-aware | ✅ Docling | ✅ Docling | ⚠️ 僅 XML |
| LlamaParse 整合 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 多模態 (圖片理解) | ❌ | ✅ | ✅ VLM | ✅ base64 | ❌ | ✅ VLM | ✅ VLM | ❌ |
| 掃描 PDF 自動分流 | ❌ | ✅ | ✅ 自動偵測 | ❌ | ❌ | ✅ | ✅ | ❌ |

**Enclave 強項**：格式覆蓋最廣（23 種），且整合了 LlamaParse 雲端高品質解析作為優先路徑。
**Enclave 弱項**：沒有 VLM 多模態理解、沒有掃描 PDF 自動分流。
**業界標竿**：RAGFlow 的 DeepDoc 模組（10 種版面 + 5 種表格標籤）是文件解析的黃金標準。

---

## 二、檢索能力

| 能力 | Enclave | RAGFlow | WeKnora | OpenKB | OpenDocuments | OpenRAG | PipesHub | OpenAI KR |
|---|---|---|---|---|---|---|---|---|
| 語義檢索 | ✅ pgvector | ✅ ES/Qdrant | ✅ 多種 | ❌ | ✅ LanceDB | ✅ OpenSearch | ✅ Qdrant | ✅ |
| BM25/關鍵字 | ✅ jieba | ✅ | ✅ POSIX regex | ❌ | ✅ FTS5 | ✅ | ✅ fastembed | ❌ |
| 混合檢索 (RRF) | ✅ | ✅ weighted | ✅ | ❌ | ✅ RRF | ✅ RRF | ✅ RRF | ❌ |
| 重排序 | ✅ Voyage | ✅ 3 種模式 | ✅ 多種 | ❌ | ✅ cross-encoder | ✅ Langflow | ✅ cross-encoder | ✅ LLM logprobs |
| HyDE 查詢擴展 | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |
| GraphRAG | ❌ | ✅ | ✅ Neo4j | ❌ | ❌ | ❌ | ✅ ArangoDB | ❌ |
| 查詢改寫 | ✅ gemma3:27b | ❌ | ✅ | ❌ | ✅ multi-query | ❌ | ❌ | ✅ |
| 父文檔檢索 | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| 快取 | ✅ Redis | ❌ | ❌ | ❌ | ✅ 3-tier | ❌ | ✅ Redis | ❌ |

**Enclave 強項**：混合檢索 + Voyage Rerank + HyDE + 查詢改寫，四層全開的檢索管線在業界屬於**前段班**。
**Enclave 弱項**：沒有 GraphRAG、沒有父文檔檢索、沒有多模型 embedding 並行策略。
**業界標竿**：OpenDocuments 的檢索管線最完整（15 種策略可開關），WeKnora 的 GraphRAG + 父文檔最成熟。

---

## 三、Agent / 工具調用框架

| 能力 | Enclave | RAGFlow | WeKnora | OpenKB | OpenDocuments | OpenRAG | PipesHub | OpenAI KR |
|---|---|---|---|---|---|---|---|---|
| Tool Registry | ✅ 2 工具 | ✅ 25+ 工具 | ✅ **30+ 工具** | ✅ Agent SDK | ❌ | ✅ 5 工具 | ✅ **30+ 工具** | ✅ 1 工具 |
| ReAct Loop | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| 可視化工作流 | ❌ | ✅ **Agent Canvas** | ❌ | ❌ | ❌ | ✅ Langflow | ✅ No-code | ❌ |
| MCP 支援 | ❌ | ✅ Server+Client | ✅ Server+Client | ❌ | ✅ Server | ✅ Server | ✅ Server+Client | ❌ |
| Agent Skills | ❌ | ❌ | ✅ 漸進式披露 | ✅ skill create | ❌ | ❌ | ✅ | ❌ |
| 多 Agent 協調 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Orchestrator | ❌ |
| 沙箱執行程式碼 | ❌ | ✅ gVisor | ✅ Docker | ❌ | ❌ | ❌ | ✅ | ❌ |

**Enclave 弱項**：這是 Enclave **最明顯的技術落差**。Tool Registry 只有 2 個內建工具（KBSearch、DocumentList），沒有 ReAct loop、沒有 MCP、沒有可視化工作流。這直接限制了它從「知識問答」升級到「業務流程 Agent」的能力。
**業界標竿**：PipesHub AI 的 Agent 框架最完整（Orchestrator + ReAct + Plan-Critique-Execute + Skills + Sandbox），WeKnora 的工具生態最豐富（30+ 工具 + MCP + Skills）。

---

## 四、多租戶與治理

| 能力 | Enclave | RAGFlow | WeKnora | OpenKB | OpenDocuments | OpenRAG | PipesHub | OpenAI KR |
|---|---|---|---|---|---|---|---|---|
| 多租戶隔離 | ✅ **完整** | ✅ 完整 | ✅ 完整 | ❌ | ⚠️ workspace | ⚠️ user-level | ✅ org-based | ❌ |
| 角色權限 (RBAC) | ✅ **5 級** | ✅ | ✅ | ❌ | ❌ | ⚠️ 可選 | ✅ | ❌ |
| 部門管理 | ✅ 樹狀 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 功能權限 (per-feature) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 功能旗標 (per-tenant) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| IP 白名單 | ✅ Admin | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Rate Limit | ✅ 滑動視窗 | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| 稽核日誌 | ✅ **完整+CSV** | ❌ | ❌ | ⚠️ log.md | ✅ audit | ❌ | ❌ | ❌ |
| 用量記錄+成本歸屬 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 配額管理 | ✅ per-tenant | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

**Enclave 強項**：這是 Enclave **最強的維度，碾壓所有開源對手**。5 級角色、部門樹、功能權限、功能旗標、IP 白名單、稽核日誌+CSV 匯出、用量記錄、配額管理——沒有任何一個開源專案同時具備這些。這是企業地端部署的硬需求，也是 Enclave 真正的護城河。

---

## 五、審批 / 人機協作

| 能力 | Enclave | RAGFlow | WeKnora | OpenKB | OpenDocuments | OpenRAG | PipesHub | OpenAI KR |
|---|---|---|---|---|---|---|---|---|
| 審批卡片/閘道 | ❌ | ❌ | ✅ MCP 審批 | ❌ | ❌ | ❌ | ✅ risk-level | ❌ |
| Human-in-the-Loop | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Agent 自動索引+審核 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

**Enclave 定位**：Enclave 有 Agent 自動索引的審核佇列（檔案入庫前人工確認分類），但**沒有業務動作的審批閘道**（如「寫入 ERP 前需主管核准」）。這是 AIAP 共通層 L5 要補的。
**業界標竿**：WeKnora 和 PipesHub 都有 MCP 工具層級的審批攔截。

---

## 六、可觀測性

| 能力 | Enclave | RAGFlow | WeKnora | OpenKB | OpenDocuments | OpenRAG | PipesHub | OpenAI KR |
|---|---|---|---|---|---|---|---|---|
| LLM 呼叫 tracing | ⚠️ RetrievalTrace | ❌ | ✅ **Langfuse OTel** | ❌ | ❌ | ❌ | ✅ Opik | ❌ |
| 問答分析儀表板 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| KB 健康度儀表板 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 成本分析+異常偵測 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Prometheus metrics | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |

**Enclave 強項**：問答分析、KB 健康度、成本分析這三個儀表板是**獨有的**，其他開源專案都沒有。
**Enclave 弱項**：沒有 OTel/Langfuse 等級的分散式 tracing。

---

## 七、評測框架

| 能力 | Enclave | RAGFlow | WeKnora | OpenKB | OpenDocuments | OpenRAG | PipesHub | OpenAI KR |
|---|---|---|---|---|---|---|---|---|
| 內建評測 | ❌ | ❌ | ❌ | ✅ skill eval | ✅ Hit@K/MRR | ❌ | ❌ | ✅ **最完整** |
| 回歸測試 | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ |

**Enclave 弱項**：完全沒有內建評測框架。
**業界標竿**：OpenAI Knowledge Retrieval 的 eval 框架最完整（自動生成 QA 資料集 + LLM judge + Hit@K/MRR/EM/F1）。

---

## 八、其他獨有能力

| 能力 | Enclave | 其他專案 |
|---|---|---|
| **內容生成 5 模板 + Word/PDF 匯出** | ✅ | ❌ 全部沒有 |
| **Mobile API (JWT refresh, push token)** | ✅ | ❌ 全部沒有 |
| **KB 版本管理 + 備份還原** | ✅ | ❌ 全部沒有 |
| **結構化問答 (EmployeeRoster)** | ✅ 雛形 | ❌ |
| **部署模式切換 (GPU/NoGPU)** | ✅ | ⚠️ RAGFlow 有 GPU profile |
| **前端 (React 19 + Vite)** | ✅ 完整 | ✅ 多數有 |
| **行動端 (React Native Expo)** | ✅ | ❌ 全部沒有 |

---

## 最終判決：Enclave 的技術實力

### 🟢 明顯領先（護城河級）

| 維度 | 領先幅度 |
|---|---|
| **多租戶治理** (RBAC + 部門 + 功能權限 + 旗標 + 配額 + 稽核) | **碾壓級** — 無開源對手 |
| **企業合規** (IP 白名單 + Rate Limit + 用量記錄 + CSV 匯出) | **碾壓級** |
| **內容生成 + 匯出** (5 模板 + Word/PDF) | **獨有** |
| **KB 生命週期管理** (版本 + 備份 + 健康度 + 缺口偵測) | **獨有** |
| **行動端支援** (Mobile API + React Native App) | **獨有** |
| **問答分析 + 成本分析儀表板** | **獨有** |

### 🟡 中等偏上（有競爭力但不獨佔）

| 維度 | 評價 |
|---|---|
| **文件解析** (23 格式 + LlamaParse) | 格式最廣，但缺 VLM/掃描分流 |
| **檢索管線** (Hybrid + RRF + Voyage + HyDE + 查詢改寫) | 前段班，缺 GraphRAG/父文檔 |
| **LLM 提供者** (OpenAI + Gemini + Ollama) | 夠用但不如 RAGFlow/WeKnora 廣泛 |

### 🔴 明顯落後（需要補強）

| 維度 | 落差 |
|---|---|
| **Agent 框架** (Tool Registry 僅 2 工具、無 ReAct/MCP/工作流) | **最大技術債** |
| **審批引擎** (無業務動作攔截) | 需從 AIAP 補 |
| **評測框架** (完全沒有) | 需從 AIAP 補或自建 |
| **分散式 Tracing** (無 OTel/Langfuse) | 企業客戶會要求 |
| **多模態** (無 VLM 圖片理解) | 製造業圖面場景需要 |

---

## 策略意涵

### 一句話總結

> **Enclave 的技術底子在「企業治理與合規」維度是碾壓級的，在「RAG 檢索」維度是前段班，但在「Agent 編排與工具生態」維度有明顯的技術債。**

### 對 Agent 產品開發的影響

這恰好對應到《製造業共通 AI Agent 盤點 v4》的判斷：

- **現在就能直接 cover**：知識問答類 Agent（§5.1 知識與培訓問答、§6.2 圖面/規格文件查詢）—— Enclave 的 RAG 管線 + 多租戶治理已經完全就緒
- **需要補強後才能 cover**：業務流程 Agent（退換貨、單據建檔、品質異常路由、CAPA/8D）—— 必須先補 Agent 框架 + 審批引擎 + MCP 連接器

### 與 AIAP 共通層的互補關係

| Enclave 弱項 | AIAP 共通層對應 | 優先序 |
|---|---|---|
| Agent 框架 (Tool Registry 薄弱) | L1 工具與連接器層 (MCP Server 群) | P0 |
| 審批引擎 (無業務動作攔截) | L5 人機協作層 (審批卡片引擎) | P0 |
| 評測框架 (完全沒有) | L7 評測層 (回歸跑分/上線閘門) | P1 |
| 分散式 Tracing | L6 可觀測性層 (OTel wrapper) | P1 |
| 政策 Schema 引擎 | L8 治理與合規層 | P0 |

---

*本文與《製造業共通 AI-Agent 盤點 v4》、《AI-Agent-共通底層架構規劃》搭配使用。*
