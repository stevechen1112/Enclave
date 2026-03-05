# Enclave — 企業私有 AI 知識大腦

> **On-premise enterprise AI knowledge brain for data-sensitive organizations.**  
> 任何不能讓資料上雲的組織 — 法律事務所、會計師事務所、醫療院所、政府機關、製造業

**版本**: Phase 13+（2026-03-05）  
**狀態**: 生產就緒

---

## 目錄

1. [為什麼是 Enclave](#為什麼是-enclave)
2. [核心功能](#核心功能)
3. [技術架構](#技術架構)
4. [前端介面導覽](#前端介面導覽)
5. [角色與權限系統](#角色與權限系統)
6. [多租戶架構](#多租戶架構)
7. [關鍵工作流程](#關鍵工作流程)
8. [快速啟動](#快速啟動)
9. [環境變數完整清單](#環境變數完整清單)
10. [API 端點參考](#api-端點參考)
11. [資料模型](#資料模型)
12. [專案結構](#專案結構)
13. [開發指南](#開發指南)
14. [開發路線圖](#開發路線圖)
15. [相關文件](#相關文件)

---

## 為什麼是 Enclave？

專業服務機構擁有高度敏感的知識資產（合約、病歷、財報、研究報告），卻無法使用 ChatGPT 等雲端工具，因為：

- 資料上傳第三方即違反保密義務
- 雲端 LLM 有訓練資料外洩風險
- 外部 API 費用隨使用量暴增
- 部分行業有法規合規要求（HIPAA、個資法）

Enclave 讓你把**整個 AI 問答引擎**部署在自己的伺服器上，資料完全不離境。

---

## 核心功能

| 模組 | 端點前綴 | 說明 |
|---|---|---|
| **AI 問答** | `/chat` | RAG 問答，串流回答（SSE），多輪對話，回饋評分 |
| **內容生成** | `/generate` | 5 種模板的 RAG 增強生成，SSE 串流，Word/PDF 匯出 |
| **報告管理** | `/generate/reports` | 生成報告的持久化儲存，分頁搜尋、釘選、CRUD |
| **文件管理** | `/documents` | 23 種格式上傳，自動解析向量化，狀態追蹤 |
| **Agent 自動索引** | `/agent` | 資料夾監控，AI 分類提案，人工審核佇列，批次排程 |
| **知識庫維護** | `/kb-maintenance` | 版本管理、健康度儀表板、缺口偵測、備份還原、分類管理 |
| **知識庫搜尋** | `/kb` | 混合語意搜尋，可指定 top_k、重排序開關 |
| **問答分析** | `/chat/analytics` | 摘要、趨勢、熱門問題、知識缺口（admin+） |
| **公司管理** | `/company` | Owner/Admin 自助管理：成員邀請、用量統計、配額檢視 |
| **管理後台** | `/admin` | 儀表板、使用者管理、系統健康（superuser） |
| **部門管理** | `/departments` | 部門 CRUD，使用者歸屬（支援內聯編輯） |
| **稽核日誌** | `/audit` | 操作日誌、用量記錄、成本統計、CSV 匯出 |
| **行動端 API** | `/mobile` | JWT 刷新、推播 token、安全事件、憑證驗證 |
| **功能旗標** | `/feature-flags` | 功能開關管理（superuser；per-tenant） |
| **組織資訊** | `/organization` | 讀取自己的組織資訊；更新僅 superuser |

---

## 技術架構

```
┌─────────────────────────────────────────────────────────────────┐
│  前端 Web     React 19 + TypeScript + Vite                       │
│  前端 Mobile  React Native (Expo)                                │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTPS / SSE
┌────────────────────────▼────────────────────────────────────────┐
│  Nginx (反向代理 + SSL 終止)                                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  FastAPI (Python 3.11)                                           │
│  ├── 認證：JWT (HS256), OAuth2 Password Flow                    │
│  ├── 中間件：CORS, Rate Limit, Tenant 隔離, Admin IP Whitelist  │
│  ├── 15 個 API 路由模組                                          │
│  └── Celery 背景任務（文件向量化、Agent 批次）                   │
└────┬───────────────────┬────────────────────────────────────────┘
     │                   │
┌────▼──────┐    ┌───────▼─────────────────────────────────────┐
│ Redis 7   │    │  PostgreSQL 15 + pgvector                    │
│ (任務佇列 │    │  ├── 多個資料表（依 migrations）              │
│  快取)    │    │  ├── tenant_id 欄位隔離（主要由應用層 query 篩選） │
└───────────┘    │  └── 1024-dim 向量欄位 (HNSW 索引)           │
                 └────────────────────────────────────────────-─┘
```

### 核心服務元件

| 元件 | 路徑 | 說明 |
|---|---|---|
| 文件解析器 | `app/services/document_parser.py` | 23 格式混合解析（LlamaParse + 原生 fallback + OCR） |
| 混合檢索引擎 | `app/services/kb_retrieval.py` | 語意 + BM25/jieba + RRF 融合 + Voyage Rerank + HyDE 查詢擴展 |
| 對話排程器 | `app/services/chat_orchestrator.py` | 串流回答 + 多輪上下文 + 來源引用 |
| 內容生成器 | `app/services/content_generator.py` | RAG 增強串流生成 + Word/PDF 匯出 |
| LLM 客戶端 | `app/services/llm_client.py` | OpenAI / Gemini / Ollama 統一介面，可熱切換（5 個獨立槽位）|
| Agent 監控 | `app/agent/file_watcher.py` | watchdog 整合，資料夾即時監控 |
| 審核佇列 | `app/agent/review_queue.py` | ReviewItem 狀態機（pending→approved/rejected/indexed） |
| 向量化任務 | `app/tasks/document_tasks.py` | Celery 非同步向量化 |

---

## 前端介面導覽

### 側欄導覽結構（4 大分組）

登入後側欄依角色顯示對應功能，分為 4 個分組：

```
┌─────────────────────┐
│  🔒 Enclave         │
├─────────────────────┤
│  工作               │ ← 所有登入使用者可見
│    AI 問答          │   /
│    內容生成         │   /generate
│    我的報告         │   /reports
│    文件管理         │   /documents
│    我的用量         │   /my-usage
├─────────────────────┤
│  管理               │ ← owner / admin / manager
│    Agent 設定       │   /agent
│    審核佇列         │   /agent/review
│    處理進度         │   /agent/progress
├─────────────────────┤
│  分析               │ ← owner / admin
│    問答分析         │   /query-analytics   (RAG KPI + 熱門問題 + 知識缺口)
│    用量統計         │   /usage             (總覽 + 部門分佈 + 成員明細)
│    稽核日誌         │   /audit
│    KB 健康度        │   /kb-health
├─────────────────────┤
│  設定               │ ← owner / admin
│    部門管理         │   /departments       (支援內聯編輯)
│    組織設定         │   /company           (儀表板 + 成員管理)
└─────────────────────┘
```

### 頁面路由總覽

| 路由 | 頁面 | 最低角色 | 說明 |
|---|---|---|---|
| `/` | ChatPage | viewer | AI 串流問答 |
| `/generate` | GeneratePage | viewer | 5 種模板內容生成 |
| `/reports` | ReportsPage | viewer | 生成報告列表（日期分組） |
| `/reports/:id` | ReportDetailPage | viewer | 報告詳情 + 匯出 |
| `/documents` | DocumentsPage | viewer | 文件上傳管理 |
| `/my-usage` | MyUsagePage | viewer | 個人用量 |
| `/agent` | AgentPage | admin | Agent 資料夾設定 |
| `/agent/review` | ReviewQueuePage | admin | 待審核清單 |
| `/agent/progress` | ProgressDashboardPage | admin | 處理進度儀表板 |
| `/query-analytics` | QueryAnalyticsPage | admin | 問答分析（概覽/熱門問題/知識缺口） |
| `/usage` | UsagePage | admin | 用量統計（總覽/部門分佈/成員明細） |
| `/audit` | AuditLogsPage | admin | 稽核日誌 |
| `/kb-health` | KBHealthPage | admin | KB 健康度（健康/分類/缺口/備份） |
| `/departments` | DepartmentsPage | admin | 部門 CRUD（樹狀，支援內聯編輯） |
| `/company` | CompanyPage | admin | 組織設定（儀表板/成員） |

> **合併重定向**：`/rag-dashboard` → `/query-analytics`、`/usage-report` → `/usage`

---

## 角色與權限系統

### 角色層級（高到低）

```
superuser          系統管理員，跨所有租戶，僅用於系統初始化與維運
    │
owner              組織擁有者，可管理本租戶所有資源
    │
admin              管理員，可管理使用者與文件，看所有稽核日誌
    │
hr                 人資 / 業務，可問答、生成、審核文件
    │
employee           一般員工，可問答與查閱文件
    │
viewer             唯讀（不可管理系統/文件），可查看與使用一般端點
```

### 各端點的最低角色要求

| 操作 | 最低角色 | 備註 |
|---|---|---|
| AI 問答（問答、串流） | viewer | 後端目前為「所有登入使用者」可用（含 viewer） |
| 文件列表 / 詳情 | viewer | employee/viewer 會套用部門範圍限制 |
| 文件上傳 / 刪除 | hr | 後端權限：owner/admin/hr |
| 內容生成 | viewer | 後端目前為所有登入使用者可用 |
| Agent（folders/review/batches） | admin | 後端檢查：owner/admin（或 superuser） |
| 回饋統計 / RAG 儀表板 | hr | 後端檢查：owner/admin/hr |
| 稽核日誌 / 用量報表（租戶層級） | hr | 後端檢查：owner/admin/hr |
| 個人用量（只看自己） | viewer | 所有登入使用者 |
| 使用者建立（POST /users/） | admin | 後端檢查：owner/admin（superuser 可跨租戶） |
| 組織更新（PUT /organization/{tenant_id}） | superuser | 讀取 /organization/me 為所有登入使用者可用 |
| 功能旗標管理（/feature-flags） | superuser | 管理端點為 superuser only |

### User 物件欄位

```json
{
  "id": "uuid",
  "email": "user@company.com",
  "full_name": "王大明",
  "role": "admin",          // owner | admin | hr | employee | viewer
  "status": "active",       // active | inactive
  "is_superuser": false,
  "tenant_id": "uuid",
  "department_id": "uuid"
}
```

---

## 多租戶架構

### 設計原則

Enclave 的資料模型採用**單資料庫多租戶（Shared Database, Shared Schema + tenant_id）**架構：

- 多數 API 端點會在 DB query 層套用 `tenant_id = current_user.tenant_id`
- 租戶之間的資料**完全隔離**，無法互相存取
- `superuser` 角色可跨租戶操作（僅系統維運使用）
- **每個組織部署一套系統**是建議的地端模式，但架構本身支援多租戶

> 注意：目前 `/api/v1/organization` 的「列出所有租戶 / 建立租戶」端點在程式中已移除，
> 預設以單組織 on-prem 使用為主；首次啟動請用 `scripts/initial_data.py` 建立 Demo Tenant。

### 典型地端部署模式

```
[部署模式 A] 單一租戶（建議）
  └── 一套 Enclave 服務 = 一個組織
      每個客戶部署獨立伺服器，資料完全隔離

[部署模式 B] 多租戶
  └── 一套 Enclave 服務 = 多個部門 / 子公司
      共用伺服器，透過 tenant_id 隔離
      適合大型集團的內部雲
```

### 初始化流程

```
1. 初始化資料（`python scripts/initial_data.py`）會建立 `Demo Tenant` + superuser
2. 使用 `POST /api/v1/auth/login/access-token` 登入取得 token
3. owner/admin 可用 `POST /api/v1/users/` 建立同租戶使用者
4. 開始上傳文件與問答
```

---

## 關鍵工作流程

### 1. 文件上傳到可問答的完整流程

```
使用者上傳文件
    │
    ▼
POST /api/v1/documents/upload
    │  (回傳 document.id + status="pending")
    │
    ▼
Celery 任務 (watcher_ingest_file_task / process_document_task)
    │
    ├── 1. 文件解析（LlamaParse / 原生解析器 / OCR）
    ├── 2. Markdown 分塊（chunk_size=1000 tokens, overlap=150）
    ├── 3. Voyage AI 嵌入（voyage-4-lite, 1024-dim）
    ├── 4. pgvector 寫入（HNSW 索引）
    └── 5. 更新 document.status = "completed"
    │
    ▼
GET /api/v1/documents/{id}  →  status: "completed"
    │
    ▼
可以問答 ✅
```

### 2. AI 問答（RAG）流程

```
使用者提問
    │
POST /api/v1/chat/chat/stream  (SSE)
    │
    ├── 1. HyDE 查詢擴展（用 LLM 生成假設性回答，增強語意搜尋）
    ├── 2. 混合檢索
    │       ├── 語意搜尋（Voyage 嵌入 + pgvector cosine 相似度）
    │       ├── BM25 關鍵詞搜尋（jieba 中文分詞）
    │       └── RRF 融合排序
    ├── 3. Voyage Rerank（重排序Top候選）
    ├── 4. 組合 Prompt（系統提示 + 檢索文件 + 對話歷史 + 使用者問題）
    ├── 5. LLM 串流生成（OpenAI GPT-4o-mini / Ollama）
    └── 6. SSE 回傳 token + 來源引用

SSE 事件格式：
  data: {"type": "status",  "content": "正在搜尋文件..."}
  data: {"type": "token",   "content": "根據您的文件，..."}
  data: {"type": "done",    "message_id": "uuid", "conversation_id": "uuid",
                            "sources": [...]}
  data: {"type": "error",   "content": "錯誤訊息"}
```

### 3. Agent 自動索引流程

Agent 支援兩種操作路徑：

**路徑 A — 主動匯入 Wizard（前端 UI 5 步驟）**
```
[Step 1] 使用者在 UI 點選本機資料夾
            │  瀏覽器讀取所有檔案（webkitdirectory）
            ▼
[Step 2] POST /api/v1/agent/scan-preview
            │  依 SCAN_LLM_PROVIDER 呼叫 AI（Gemini / OpenAI / Ollama）
            │  讀取前端傳入的內容取樣
            │  生成每個子資料夾的繁體中文 AI 摘要
            ▼
[Step 3] 前端顯示確認清單（資料夾名稱 + AI 摘要 + 勾選框）
            │  使用者可取消勾選不需要的子資料夾
            ▼
[Step 4] 依序 POST /api/v1/documents/upload（並發上限 3）
            │  每個檔案上傳後後端自動觸發向量化
            ▼
[Step 5] 顯示完成結果（成功 N / 失敗 M + 失敗清單）
```

**路徑 B — 常駐監控（伺服器端 watchdog）**
```
磁碟資料夾（AGENT_WATCH_FOLDERS）
    │
    ▼
file_watcher（watchdog）
    │  偵測到新增 / 修改的檔案（防抖 5 秒）
    ▼
review_queue.enqueue(proposal, tenant_id)
    │  建立 ReviewItem（status=pending）
    ▼
GET /api/v1/agent/review  →  審核員看到佇列
    │
    ├── [核准] POST /api/v1/agent/review/{id}/approve
    │       └── 觸發向量化任務 → document.status="completed"
    │
    ├── [拒絕] POST /api/v1/agent/review/{id}/reject
    │
    └── [修改] POST /api/v1/agent/review/{id}/modify
            └── 修改分類後核准

批次排程（AGENT_BATCH_HOUR，每天凌晨執行）：
  POST /api/v1/agent/batches/trigger
  GET  /api/v1/agent/batches/report  →  PDF 批次報告
```

### 3.5 部署模式切換（GPU / NoGPU 固定策略）

管理者可在「公司管理 → 部署模式」切換執行策略，切換後**下一次請求立即生效**（不需重啟）。

```
NoGPU 模式（沿用目前 .env）
  ①② 主 LLM      → 依 `LLM_PROVIDER` 對應模型（Gemini 用 `GEMINI_MODEL`、OpenAI 用 `OPENAI_MODEL`、Ollama 用 `OLLAMA_MODEL`）
  ③ 內部改寫      → 依 `INTERNAL_LLM_PROVIDER` 對應模型（`INTERNAL_GEMINI_MODEL` / `INTERNAL_OPENAI_MODEL` / `INTERNAL_OLLAMA_MODEL`）
  ④ 掃描摘要      → 依 `SCAN_LLM_PROVIDER` 對應模型（`SCAN_GEMINI_MODEL` / `SCAN_OPENAI_MODEL` / `OLLAMA_SCAN_MODEL`）
  ⑤ Embedding    → 依 `EMBEDDING_PROVIDER` 對應模型（Voyage=`VOYAGE_MODEL`、Ollama=`OLLAMA_EMBED_MODEL`）

  目前專案（你現在的 NoGPU 設定）範例：
  - ①② 主 LLM：`gemini-3-flash-preview`
  - ③ 內部改寫：`gemini-3.1-flash-lite-preview`
  - ④ 掃描摘要：`gemini-3.1-flash-lite-preview`
  - ⑤ Embedding：以當前 `EMBEDDING_PROVIDER` 為準（可在「公司管理 → 部署模式」或 `GET /api/v1/company/deployment-mode` 查看實際生效值）

GPU 模式（固定 preset）
  ①② 主 LLM      → provider=`ollama`，model=`qwen3:14b`（固定）
  ③ 內部改寫      → provider=`ollama`，model=`qwen3:14b`（固定）
  ④ 掃描摘要      → provider=`ollama`，model=`qwen3:14b`（固定）
  ⑤ Embedding    → provider=`ollama`，model=`bge-m3:latest`（固定）

  對應說明：
  - GPU 模式下，以上 4 組會由系統 preset 直接覆蓋生效（不是讀 `.env` 變數）
  - 可用 `GET /api/v1/company/deployment-mode` 查看目前實際生效值
```

> 模式值儲存在 `feature_flags.key=deployment_mode` 的 metadata，不需修改 `.env`。

### 4. 內容生成流程

```
POST /api/v1/generate/stream
  {
    "template": "case_summary",      // 見下方模板列表
    "user_prompt": "請摘要本案要點",
    "context_query": "合約糾紛要點",  // RAG 檢索用語
    "document_ids": ["uuid1", ...],  // 可選：指定文件直接帶入
    "max_tokens": 3000
  }

    │
    ├── 1. 文件內容帶入（document_ids 指定 + context_query RAG 檢索）
    ├── 2. 依模板組合 System Prompt
    ├── 3. LLM 串流生成
    └── 4. SSE 回傳 content token

生成完畢後可匯出：
  POST /api/v1/generate/export/docx  →  下載 .docx
  POST /api/v1/generate/export/pdf   →  下載 .pdf
```

**可用模板**：

| template | 說明 |
|---|---|
| `draft_response` | 函件 / 回函草稿 |
| `case_summary` | 案件 / 專案摘要 |
| `meeting_minutes` | 會議記錄整理 |
| `analysis_report` | 分析報告 |
| `faq_draft` | FAQ 草稿 |

---

## 快速啟動

### 前置需求

- Docker Engine 24+ & Docker Compose v2
- 至少 4GB RAM（推薦 8GB）
- Python 3.11+（本機開發用）
- Node.js 20+（前端開發用）

### 1. 複製並設定環境變數

```bash
cp .env.example .env
```

**最少必填的變數**（其餘均有預設值）：

```env
SECRET_KEY=<用以下指令產生: python -c "import secrets; print(secrets.token_urlsafe(48))">
ORGANIZATION_NAME=我的公司

# 選擇一個 LLM Provider（推薦 Gemini，有免費層）
LLM_PROVIDER=gemini
GEMINI_API_KEY=<申請: https://aistudio.google.com/apikey>

# 掃資料夾 AI 摘要（無 GPU 必填）
SCAN_LLM_PROVIDER=gemini
# SCAN_GEMINI_MODEL 預設 gemini-3.1-flash-lite-preview，不需另外設定

# 查詢改寫內部任務
INTERNAL_LLM_PROVIDER=gemini
# INTERNAL_GEMINI_MODEL 預設 gemini-3.1-flash-lite-preview，不需另外設定

# Embedding（本地免費方案，需先 ollama pull bge-m3）
EMBEDDING_PROVIDER=ollama
# 或使用 Voyage AI 雲端 Embedding：
# EMBEDDING_PROVIDER=voyage
# VOYAGE_API_KEY=<申請: https://www.voyageai.com/>
```

### 2. 啟動所有服務

```bash
docker compose up -d
```

首次啟動約需 2-3 分鐘（下載映像 + 初始化）。

```bash
# 確認全部健康
docker compose ps
```

| 服務容器 | 對外埠 | 說明 |
|---|---|---|
| `frontend` | 5173 | React 前端 |
| `api` | 8000 | FastAPI 後端 |
| `db` | 5432 | PostgreSQL + pgvector |
| `redis` | 6379 | Redis 任務佇列 |
| `worker` | — | Celery 背景工作者 |

### 3. 初始化資料庫與第一個超級使用者

```bash
# 跑 migration
docker compose exec api alembic upgrade head

# 建立 superuser（email/password 來自 .env 的 FIRST_SUPERUSER_*）
docker compose exec api python scripts/initial_data.py
```

`scripts/initial_data.py` 預設會：

- 建立一個名為 `Demo Tenant` 的租戶（若不存在）
- 建立 superuser（同時具備 `is_superuser=true` 與 `role=owner`）

### 4. 開啟系統

| 入口 | 網址 |
|---|---|
| 前端 Web | http://localhost:5173 |
| API 文件（Swagger） | http://localhost:8000/docs |
| API 文件（ReDoc） | http://localhost:8000/redoc |
| 健康檢查 | http://localhost:8000/health |

預設登入：`admin@example.com` / `admin123`（務必在生產環境修改）

### 5. 建立使用者（首次設定）

目前後端 `POST /api/v1/users/` 的權限為 **owner/admin**（superuser 也可）。

```bash
# 先取得 token
curl -X POST http://localhost:8000/api/v1/auth/login/access-token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=admin123"

# tenant_id 可用 /api/v1/organization/me 查到

# 建立同租戶的 admin 使用者
curl -X POST http://localhost:8000/api/v1/users/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@company.com", "password": "StrongPass123!",
       "full_name": "系統管理員", "tenant_id": "<tenant_id>", "role": "admin"}'
```

---

## 環境變數完整清單

### 核心

| 變數 | 預設值 | 說明 |
|---|---|---|
| `APP_NAME` | `Enclave` | 應用名稱 |
| `APP_ENV` | `development` | `development` / `staging` / `production` |
| `ORGANIZATION_NAME` | `My Organization` | 顯示在 UI 的組織名稱 |
| `SECRET_KEY` | *(必填)* | JWT 簽名密鑰，≥32 字元 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `11520` (8天) | Token 有效期 |
| `FIRST_SUPERUSER_EMAIL` | `admin@example.com` | 初始 superuser 帳號 |
| `FIRST_SUPERUSER_PASSWORD` | `admin123` | 初始 superuser 密碼 |

### 資料庫

| 變數 | 預設值 | 說明 |
|---|---|---|
| `POSTGRES_SERVER` | `localhost` | PostgreSQL 主機 |
| `POSTGRES_USER` | `postgres` | 資料庫帳號 |
| `POSTGRES_PASSWORD` | `postgres` | 資料庫密碼（生產必改） |
| `POSTGRES_DB` | `enclave` | 資料庫名稱 |

### AI 服務

> 系統有 **5 個獨立 LLM 槽位**，可分別設定不同模型與提供商：  
> ①② 問答/生成（`LLM_PROVIDER`）、③ 查詢改寫（`INTERNAL_LLM_PROVIDER`）、  
> ④ 掃資料夾摘要（`SCAN_LLM_PROVIDER`）、⑤ 向量化（`EMBEDDING_PROVIDER`）

> 補充：若 `deployment_mode=gpu`，系統會覆蓋為固定 Qwen preset（主/副/掃描 `qwen3:14b`、Embedding `bge-m3:latest`）。

**主力 LLM（① ② 問答 + 生成）**

| 變數 | 預設值 | 說明 |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` / `gemini` / `ollama` |
| `GEMINI_API_KEY` | *(gemini 模式必填)* | Google Gemini API 金鑰 |
| `GEMINI_MODEL` | `gemini-3-flash-preview` | Gemini 模型名稱 |
| `OPENAI_API_KEY` | *(openai 模式必填)* | OpenAI API 金鑰 |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI 模型名稱 |
| `OPENAI_TEMPERATURE` | `0.3` | 問答溫度（低=精確） |
| `OPENAI_MAX_TOKENS` | `1500` | 問答最大 token |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 服務位址 |
| `OLLAMA_MODEL` | `llama3.2` | Ollama 主力模型 |

**內部任務 LLM（③ 查詢改寫 / 對話分類）**

| 變數 | 預設值 | 說明 |
|---|---|---|
| `INTERNAL_LLM_PROVIDER` | `ollama` | `ollama` / `gemini` / `openai` |
| `INTERNAL_OLLAMA_MODEL` | `gemma3:27b` | 本地內部任務模型 |
| `INTERNAL_GEMINI_MODEL` | `gemini-3.1-flash-lite-preview` | Gemini 輕量內部任務模型 |
| `INTERNAL_OPENAI_MODEL` | `gpt-4o-mini` | OpenAI 內部任務模型 |

**掃資料夾 AI 摘要（④ Wizard Step 2）**

| 變數 | 預設值 | 說明 |
|---|---|---|
| `SCAN_LLM_PROVIDER` | `ollama` | `ollama` / `gemini` / `openai`（無 GPU 改為 `gemini`）|
| `SCAN_GEMINI_MODEL` | `gemini-3.1-flash-lite-preview` | 雲端掃描摘要模型 |
| `SCAN_OPENAI_MODEL` | `gpt-4o-mini` | OpenAI 掃描摘要模型 |
| `OLLAMA_SCAN_URL` | `http://host.docker.internal:11434` | Ollama 掃描服務位址 |
| `OLLAMA_SCAN_MODEL` | `gemma3:27b` | Ollama 掃描摘要模型 |

**Embedding（⑤ 向量化）**

| 變數 | 預設值 | 說明 |
|---|---|---|
| `EMBEDDING_PROVIDER` | `ollama` | `voyage` / `ollama` |
| `VOYAGE_API_KEY` | *(voyage 模式必填)* | Voyage AI 嵌入金鑰 |
| `VOYAGE_MODEL` | `voyage-4-lite` | Voyage 嵌入模型 |
| `OLLAMA_EMBED_MODEL` | `bge-m3` | 本地嵌入模型（品質媲美 Voyage）|
| `EMBEDDING_DIMENSION` | `1024` | 向量維度（需與模型對應）|

**文件解析**

| 變數 | 預設值 | 說明 |
|---|---|---|
| `LLAMAPARSE_API_KEY` | *(選填)* | LlamaParse 文件解析金鑰 |
| `LLAMAPARSE_ENABLED` | `true` | 停用則使用原生解析器 |

### 檢索

| 變數 | 預設值 | 說明 |
|---|---|---|
| `RETRIEVAL_MODE` | `hybrid` | `semantic` / `keyword` / `hybrid` |
| `RETRIEVAL_MIN_SCORE` | `0.0` | 最低相似度閾值 |
| `RETRIEVAL_RERANK` | `true` | 是否啟用 Voyage Rerank |
| `RETRIEVAL_TOP_K` | `5` | 預設檢索數量 |
| `RETRIEVAL_CACHE_TTL` | `300` | 檢索快取秒數 |

### 文件處理

| 變數 | 預設值 | 說明 |
|---|---|---|
| `UPLOAD_DIR` | `./uploads` | 上傳檔案儲存路徑 |
| `MAX_FILE_SIZE` | `52428800` (50MB) | 單檔案大小上限 |
| `CHUNK_SIZE` | `1000` | 分塊大小（tokens） |
| `CHUNK_OVERLAP` | `150` | 分塊重疊（tokens） |
| `OCR_LANGS` | `chi_tra+eng` | OCR 語言（繁體中文+英文） |

### Agent（Phase 10）

| 變數 | 預設值 | 說明 |
|---|---|---|
| `AGENT_WATCH_ENABLED` | `false` | 是否啟用資料夾監控 |
| `AGENT_WATCH_FOLDERS` | `""` | 逗號分隔的監控路徑 |
| `AGENT_SCAN_INTERVAL` | `60` | 掃描間隔（秒） |
| `AGENT_BATCH_HOUR` | `2` | 排程批次時間（凌晨幾點） |
| `AGENT_MAX_CPU_PERCENT`| `50.0` | CPU 使用上限 |

### 內容生成（Phase 11）

| 變數 | 預設值 | 說明 |
|---|---|---|
| `GENERATION_MAX_TOKENS` | `3000` | 生成文件最大 token |
| `GENERATION_TEMPERATURE` | `0.4` | 生成溫度（略高於問答） |

### 安全與限流

| 變數 | 預設值 | 說明 |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | 是否啟用限流 |
| `RATE_LIMIT_GLOBAL_PER_IP` | `200` | 每 IP 每分鐘全域請求上限 |
| `RATE_LIMIT_PER_USER` | `60` | 每使用者每分鐘請求上限 |
| `RATE_LIMIT_CHAT_PER_USER` | `20` | 每使用者每分鐘問答上限 |
| `ADMIN_IP_WHITELIST_ENABLED` | `false` | 管理員 IP 白名單 |
| `ADMIN_IP_WHITELIST` | `127.0.0.1,...` | 允許的管理員 IP |

---

## API 端點參考

所有端點前綴：`/api/v1/`  
認證方式：`Authorization: Bearer <access_token>`

### 認證 `/auth`

| 方法 | 路徑 | 說明 | 需要認證 |
|---|---|---|---|
| POST | `/auth/login/access-token` | 登入，取得 JWT token | ❌ |

**登入請求**（form-urlencoded）：
```
username=user@example.com&password=YourPassword
```
**登入回應**：
```json
{"access_token": "eyJ...", "token_type": "bearer"}
```

### 使用者 `/users`

| 方法 | 路徑 | 說明 | 最低角色 |
|---|---|---|---|
| GET | `/users/me` | 取得自己的資料 | viewer |
| POST | `/users/` | 建立使用者（同租戶） | admin |

### 組織管理 `/organization`

| 方法 | 路徑 | 說明 | 最低角色 |
|---|---|---|---|
| GET | `/organization/me` | 取得自己所屬組織 | viewer |
| GET | `/organization/{tenant_id}` | 取得組織詳情（僅限自己的 tenant） | viewer |
| PUT | `/organization/{tenant_id}` | 更新組織名稱/描述 | superuser |

### 後台管理 `/admin`

| 方法 | 路徑 | 說明 | 最低角色 |
|---|---|---|---|
| GET | `/admin/dashboard` | 組織儀表板（統計數據） | superuser |
| GET | `/admin/users` | 搜尋組織內使用者 | superuser |
| POST | `/admin/users/invite` | 邀請（建立）使用者 | superuser |
| PUT | `/admin/users/{id}` | 更新使用者 | superuser |
| DELETE | `/admin/users/{id}` | 停用使用者 | superuser |
| GET | `/admin/system/health` | 系統健康狀態 | superuser |

### 文件 `/documents`

| 方法 | 路徑 | 說明 | 最低角色 |
|---|---|---|---|
| POST | `/documents/upload` | 上傳文件（multipart） | hr |
| GET | `/documents/` | 列出文件（支援 department_id 篩選） | viewer |
| GET | `/documents/{document_id}` | 取得文件詳情 / 狀態 | viewer |
| DELETE | `/documents/{document_id}` | 刪除文件 | hr |

**文件狀態**：`pending` → `processing` → `completed` / `failed`

**支援格式**（23種）：  
PDF, DOCX, DOC, XLSX, XLS, PPTX, PPT, TXT, MD, CSV, JSON, XML, HTML, RTF, ODT, ODS, ODP, PNG, JPG, JPEG, TIFF, BMP, GIF

### AI 問答 `/chat`

| 方法 | 路徑 | 說明 | 最低角色 |
|---|---|---|---|
| POST | `/chat/chat` | 同步問答（一次性回應） | viewer |
| POST | `/chat/chat/stream` | SSE 串流問答 | viewer |
| GET | `/chat/conversations` | 列出對話歷史 | viewer |
| GET | `/chat/conversations/search` | 搜尋對話（關鍵詞） | viewer |
| GET | `/chat/conversations/{id}` | 取得對話詳情 | viewer |
| GET | `/chat/conversations/{id}/messages` | 取得對話訊息列表 | viewer |
| DELETE | `/chat/conversations/{id}` | 刪除對話 | viewer |
| GET | `/chat/conversations/{id}/export` | 匯出對話（Markdown） | viewer |
| POST | `/chat/feedback` | 提交回饋（評分） | viewer |
| GET | `/chat/feedback/stats` | 回饋統計 | hr |
| GET | `/chat/dashboard/rag` | RAG 效能儀表板 | hr |
| GET | `/chat/analytics/summary` | 問答分析摘要 | admin |
| GET | `/chat/analytics/trend` | 問答趨勢 | admin |
| GET | `/chat/analytics/top-queries` | 熱門問題 | admin |
| GET | `/chat/analytics/unanswered` | 未回答問題 | admin |

**SSE 串流問答請求**：
```json
{
  "question": "這份合約的付款條件是什麼？",
  "conversation_id": "uuid（選填，延續對話）",
  "top_k": 5
}
```

### 內容生成 `/generate`

| 方法 | 路徑 | 說明 | 最低角色 |
|---|---|---|---|
| GET | `/generate/templates` | 取得可用模板列表 | viewer |
| POST | `/generate/stream` | SSE 串流生成 | viewer |
| POST | `/generate/export/docx` | 匯出為 Word | viewer |
| POST | `/generate/export/pdf` | 匯出為 PDF | viewer |

### 報告管理 `/generate/reports`

| 方法 | 路徑 | 說明 | 最低角色 |
|---|---|---|---|
| GET | `/generate/reports` | 列出我的報告（分頁、搜尋、篩選模板） | viewer |
| GET | `/generate/reports/{id}` | 查看單篇報告詳情 | viewer |
| POST | `/generate/reports` | 手動建立報告（串流完成後自動呼叫） | viewer |
| PATCH | `/generate/reports/{id}` | 更新報告（標題 / 釘選 / 內容） | viewer |
| DELETE | `/generate/reports/{id}` | 刪除報告 | viewer |

### Agent 自動索引 `/agent`

| 方法 | 路徑 | 說明 | 最低角色 |
|---|---|---|---|
| GET | `/agent/status` | Agent 運行狀態 | admin |
| POST | `/agent/start` | 啟動 Agent | admin |
| POST | `/agent/stop` | 停止 Agent | admin |
| POST | `/agent/scan` | 手動觸發掃描 | admin |
| GET | `/agent/folders` | 列出監控資料夾 | admin |
| POST | `/agent/folders` | 新增監控資料夾 | admin |
| DELETE | `/agent/folders/{id}` | 刪除監控資料夾 | admin |
| PATCH | `/agent/folders/{id}/toggle` | 啟用/停用資料夾 | admin |
| GET | `/agent/review` | 取得待審核清單 | admin |
| POST | `/agent/review/{id}/approve` | 核准並觸發向量化 | admin |
| POST | `/agent/review/{id}/reject` | 拒絕文件 | admin |
| POST | `/agent/review/{id}/modify` | 修改分類後核准 | admin |
| POST | `/agent/review/batch-approve` | 批量核准 | admin |
| GET | `/agent/browse` | 瀏覽伺服器端目錄結構（資料夾選擇器用） | admin |
| POST | `/agent/pick-local-folder` | 開啟本機 OS 原生資料夾選擇視窗 | admin |
| POST | `/agent/scan-preview` | Wizard：AI 分析子資料夾並生成摘要（支援 Gemini / OpenAI / Ollama，由 `SCAN_LLM_PROVIDER` 決定）| admin |
| GET | `/agent/batches` | 批次處理歷史 | admin |
| POST | `/agent/batches/trigger` | 手動觸發批次 | admin |
| GET | `/agent/batches/report` | 下載批次 PDF 報告 | admin |

### 知識庫維護 `/kb-maintenance`

| 方法 | 路徑 | 說明 | 最低角色 |
|---|---|---|---|
| GET | `/kb-maintenance/kb/health` | KB 健康度儀表板 | admin |
| GET | `/kb-maintenance/kb/usage-report` | 知識庫使用統計報告 | viewer |
| POST | `/kb-maintenance/kb/integrity/scan` | 觸發完整性檢查 | admin |
| GET | `/kb-maintenance/kb/integrity/reports` | 完整性報告列表 | viewer |
| GET | `/kb-maintenance/documents/{id}/versions` | 文件版本列表 | viewer |
| POST | `/kb-maintenance/documents/{id}/reupload` | 重新上傳（建版） | hr |
| GET | `/kb-maintenance/documents/{id}/diff` | 版本差異比對 | viewer |
| GET | `/kb-maintenance/kb/gaps` | 知識缺口列表 | viewer |
| POST | `/kb-maintenance/kb/gaps/scan` | 觸發缺口掃描 | admin |
| POST | `/kb-maintenance/kb/gaps/{id}/resolve` | 標記缺口已解決 | viewer |
| GET | `/kb-maintenance/kb/categories` | 分類樹狀列表 | viewer |
| POST | `/kb-maintenance/kb/categories` | 建立分類 | admin |
| PUT | `/kb-maintenance/kb/categories/{id}` | 更新分類 | admin |
| DELETE | `/kb-maintenance/kb/categories/{id}` | 刪除分類 | admin |
| GET | `/kb-maintenance/kb/categories/{id}/revisions` | 分類修改歷史 | viewer |
| POST | `/kb-maintenance/kb/categories/{id}/rollback/{rev}` | 回滾至指定版本 | viewer |
| GET | `/kb-maintenance/kb/backups` | 備份列表 | viewer |
| POST | `/kb-maintenance/kb/backups` | 建立備份 | admin |
| POST | `/kb-maintenance/kb/backups/restore` | 還原備份 | admin |

### 稽核日誌 `/audit`

| 方法 | 路徑 | 說明 | 最低角色 |
|---|---|---|---|
| GET | `/audit/logs` | 操作日誌（可篩選） | hr |
| GET | `/audit/logs/export` | 匯出日誌 CSV | hr |
| GET | `/audit/usage/summary` | 用量摘要 | hr |
| GET | `/audit/usage/by-action` | 各操作類型用量 | hr |
| GET | `/audit/usage/records` | 詳細用量記錄 | hr |
| GET | `/audit/usage/export` | 匯出用量 CSV | hr |
| GET | `/audit/usage/me/summary` | 自己的用量摘要 | viewer |
| GET | `/audit/usage/me/by-action` | 自己的操作用量 | viewer |

### 公司自助管理 `/company`

| 方法 | 路徑 | 說明 | 最低角色 |
|---|---|---|---|
| GET | `/company/dashboard` | 公司儀表板（成員數、配額、最近活動） | admin |
| GET | `/company/profile` | 公司資訊 | admin |
| GET | `/company/quota` | 配額狀態 | admin |
| POST | `/company/users/invite` | 邀請新成員 | admin |
| GET | `/company/users` | 列出公司成員 | admin |
| PUT | `/company/users/{user_id}` | 更新成員資料（角色、狀態） | admin |
| DELETE | `/company/users/{user_id}` | 停用成員 | admin |
| GET | `/company/usage/summary` | 組織用量摘要 | admin |
| GET | `/company/usage/by-user` | 每位使用者用量明細 | admin |
| GET | `/company/deployment-mode` | 取得目前部署模式與生效中的 LLM preset | admin |
| PUT | `/company/deployment-mode` | 切換部署模式（`gpu` / `nogpu`） | admin |

---

## 資料模型

### 主要資料表（依 migrations）

| 資料表 | 模型 | 說明 |
|---|---|---|
| `tenants` | Tenant | 組織 / 租戶 |
| `users` | User | 使用者（含角色、部門、superuser） |
| `departments` | Department | 部門（樹狀） |
| `documents` | Document | 文件元資料 |
| `documentchunks` | DocumentChunk | 文件分塊 + 向量嵌入（pgvector） |
| `conversations` | Conversation | 對話 |
| `messages` | Message | 對話訊息（user/assistant） |
| `retrievaltraces` | RetrievalTrace | RAG 檢索追蹤（sources_json 等） |
| `auditlogs` | AuditLog | 操作日誌 |
| `usagerecords` | UsageRecord | 用量記錄（tokens/latency/cost） |
| `generated_reports` | GeneratedReport | 內容生成報告持久化（標題/模板/內容/釘選） |
| `featurepermissions` | FeaturePermission | 角色 × 功能允許矩陣 |
| `tenant_sso_configs` | TenantSSOConfig | 租戶 SSO 設定 |
| `feature_flags` | FeatureFlag | 功能旗標（superuser 管理） |
| `customdomains` | CustomDomain | 自訂網域（租戶） |
| `chat_feedbacks` | ChatFeedback | 回饋評分 |
| `watch_folders` | WatchFolder | Agent 監控資料夾 |
| `review_items` | ReviewItem | 待審核文件佇列 |
| `documentversions` | DocumentVersion | 文件版本歷史 |
| `categories` | Category | 文件分類（樹狀） |
| `categoryrevisions` | CategoryRevision | 分類修改歷史 |
| `kbbackups` | KBBackup | KB 備份任務 |
| `knowledgegaps` | KnowledgeGap | 知識缺口記錄 |
| `integrityreports` | IntegrityReport | 完整性掃描報告 |

### 關鍵欄位說明

**Document.status**：`pending` / `processing` / `completed` / `failed`

**ReviewItem.status**：`pending` / `approved` / `rejected` / `modified` / `indexed`

**UsageRecord.action_type**：`chat_query` / `content_generate` / `document_upload` / `kb_search`

---

## 專案結構

```
Enclave/
├── app/
│   ├── api/
│   │   ├── deps.py             # 依賴注入（get_db, get_current_user）
│   │   ├── deps_permissions.py # RBAC 權限檢查（require_*）
│   │   └── v1/
│   │       ├── api.py          # 路由總覽（16 個 router）
│   │       └── endpoints/      # 16 個端點模組
│   │           ├── auth.py
│   │           ├── users.py
│   │           ├── tenants.py  # 組織資訊（單一組織；PUT 僅 superuser）
│   │           ├── admin.py    # 地端管理後台 API（superuser 專用）
│   │           ├── company.py  # 公司自助管理（owner/admin）
│   │           ├── documents.py
│   │           ├── kb.py
│   │           ├── chat.py     # 問答 + 串流 + 多輪 + 分析
│   │           ├── generate.py # 內容生成 + 匯出
│   │           ├── reports.py  # 報告管理 CRUD
│   │           ├── agent.py    # Agent + 審核佇列
│   │           ├── kb_maintenance.py
│   │           ├── audit.py
│   │           ├── analytics.py
│   │           ├── departments.py
│   │           ├── feature_flags.py
│   │           ├── sso.py
│   │           └── mobile.py
│   ├── models/                 # SQLAlchemy 模型
│   ├── schemas/                # Pydantic v2 Schema
│   ├── crud/                   # 資料存取層
│   ├── services/               # 業務邏輯
│   │   ├── document_parser.py  # 文件解析（多格式）
│   │   ├── kb_retrieval.py     # 混合檢索引擎
│   │   ├── chat_orchestrator.py
│   │   ├── content_generator.py
│   │   └── llm_client.py
│   ├── agent/                  # Agent 模組
│   │   ├── file_watcher.py
│   │   ├── scheduler.py
│   │   ├── tool_registry.py
│   │   ├── review_queue.py
│   │   └── classifier.py
│   ├── tasks/                  # Celery 任務
│   │   └── document_tasks.py
│   ├── db/
│   │   ├── migrations/versions/ # Alembic migration
│   │   └── session.py
│   ├── middleware/
│   └── config.py               # 所有設定（含預設值）
├── frontend/                   # Web 前端
│   └── src/
│       ├── pages/
│       │   ├── ChatPage.tsx          # AI 問答（主頁）
│       │   ├── GeneratePage.tsx      # 內容生成
│       │   ├── ReportsPage.tsx       # 報告列表（日期分組）
│       │   ├── ReportDetailPage.tsx  # 報告詳情
│       │   ├── DocumentsPage.tsx     # 文件管理
│       │   ├── MyUsagePage.tsx       # 個人用量
│       │   ├── UsagePage.tsx         # 用量統計（總覽/部門/成員）
│       │   ├── AuditLogsPage.tsx     # 稽核日誌
│       │   ├── QueryAnalyticsPage.tsx # 問答分析（RAG KPI/熱門/缺口）
│       │   ├── KBHealthPage.tsx      # KB 健康度
│       │   ├── AgentPage.tsx         # Agent 設定
│       │   ├── ReviewQueuePage.tsx   # 審核佇列
│       │   ├── ProgressDashboardPage.tsx # 處理進度
│       │   ├── DepartmentsPage.tsx   # 部門管理（支援內聯編輯）
│       │   ├── CompanyPage.tsx       # 組織設定（儀表板/成員）
│       │   └── LoginPage.tsx
│       ├── components/
│       │   └── Layout.tsx            # 側欄導覽（4 分組，角色過濾）
│       ├── api.ts              # API 客戶端
│       └── types.ts            # TypeScript 型別
├── mobile/                     # React Native (Expo)
│   └── src/
│       ├── screens/
│       ├── api.ts
│       └── types.ts
├── alembic/versions/           # Alembic migration
├── docker-compose.yml          # 開發環境
├── docker-compose.prod.yml     # 生產環境
├── scripts/
│   ├── initial_data.py         # 初始化 superuser
│   ├── run_tests.py            # 整合測試腳本
│   └── ...
└── test-data/                  # 測試文件與問題集
```

---

## 開發指南

### 本機開發環境

```bash
# 建立 Python 虛擬環境
python -m venv .venv
.venv\Scripts\activate  # Windows

# 安裝依賴
pip install -r requirements.txt

# 啟動資料庫（Docker）
docker compose up db redis -d

# 跑 migration
alembic upgrade head

# 啟動 API
uvicorn app.main:app --reload --port 8000

# 啟動 Celery worker（另開終端）
celery -A app.celery_app worker --loglevel=info

# 啟動前端（另開終端）
cd frontend && npm install && npm run dev
```

### Migration 管理

主鏈位於 `app/db/migrations/versions/`（alembic.ini 指向此目錄）：

```
450ae450e023  初始 Schema（所有核心資料表）
  └─► 84a829cdf24b  部門 + 功能權限
        └─► f7859742ce5d  租戶 SSO 設定
              └─► eb7fe95812e8  功能旗標
                    └─► a1b2c3d4e5f6  pgvector 嵌入欄位
                          └─► c7c9c43b1a3d  Custom Domains
                                └─► d1e2f3a4b5c6  Phase 7/10/13 資料表 ← HEAD
```

```bash
# 套用所有 migration
alembic upgrade head

# 產生新 migration
alembic revision --autogenerate -m "描述"

# 回滾一步
alembic downgrade -1
```

### 產生安全密鑰

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 測試

```bash
# 單元測試
pytest tests/

# 整合測試（需要運行中的 API）
python scripts/run_tests.py

# 指定特定 phase
python scripts/run_tests.py --phase 0 --phase 1

# 雲端環境測試
ENCLAVE_BASE_URL=http://your-server python scripts/run_tests.py
```

---

## 開發路線圖

| Phase | 範圍 | 狀態 |
|---|---|---|
| 1-2 | 帳號管理、認證、多租戶 | ✅ 完成 |
| 3-4 | 文件上傳解析、RAG 檢索引擎 | ✅ 完成 |
| 5-6 | AI 問答串流、對話管理、回饋 | ✅ 完成 |
| 7-8 | 稽核日誌、用量追蹤、成本分析 | ✅ 完成 |
| 9 | SaaS → On-Premise 轉型基礎 | ✅ 完成 |
| 10 | Agent 主動索引（監控、分類、審核、排程） | ✅ 完成 |
| 11 | 內容生成引擎（RAG 增強、串流、匯出） | ✅ 完成 |
| 11-2 | 報告持久化（建模、CRUD、日期分組） | ✅ 完成 |
| 12 | 行動端 App（React Native + Expo） | ✅ 完成 |
| 13 | KB 維護（版本、健康度、缺口、備份、分類）| ✅ 完成 |
| 13+ | UX 優化（側欄分組、頁面合併、分析整合） | ✅ 完成 |
| 14 | 進階 Agent（Rule Engine、Digest、Multi-step） | 🔲 計畫中 |
| 15 | 協作功能（標註、分享、知識圖譜） | 🔲 計畫中 |

---

## 相關文件

| 文件 | 說明 |
|---|---|
| [docs/API_GUIDE.md](docs/API_GUIDE.md) | API 使用指南 |
| [docs/API_DEVELOPER_GUIDE.md](docs/API_DEVELOPER_GUIDE.md) | 開發者整合指南 |
| [docs/USER_MANUAL.md](docs/USER_MANUAL.md) | 使用手冊 |
| [docs/LINODE_DEPLOYMENT.md](docs/LINODE_DEPLOYMENT.md) | Linode 部署教學 |
| [docs/OPS_SOP.md](docs/OPS_SOP.md) | 維運 SOP |
| [INTEGRATION_AUDIT_REPORT.md](INTEGRATION_AUDIT_REPORT.md) | 整合審查報告（Phase 1-13） |
| [INTEGRATION_FIX_REPORT.md](INTEGRATION_FIX_REPORT.md) | 整合修復完成報告 |

---

## 授權

Enclave is proprietary software. All rights reserved.
