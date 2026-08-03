# Enclave 2.0 — 地端企業知識 Control Plane

> 客戶只面對**一套**身分、權限、知識庫生命週期、問答與維運。  
> 高品質解析、企業來源同步、知識編譯以**可開關的 sidecar 能力包**接入；資料權威與最終授權留在 Enclave。

| 項目 | 狀態（2026-08-03） |
|------|-------------------------|
| 產品線名稱 | **Enclave 2.0**（Triple Injection：RAGFlow + PipesHub + WeKnora） |
| 本機核心／計畫可自動化出口 | **已完成**（code 閘門 32/32、檢查點 67/73、false_green=0） |
| 能力啟用與價值證明 | **已閉環**（見 `docs/CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md`／`docs/CAPABILITY_CLAIMS.md`） |
| UI／UX 2.0 IA | **已落地**（總覽｜問答｜知識｜治理｜系統；知識含 Wiki 瀏覽＋管理員編輯） |
| 本機 Pilot DB | **單一租戶乾淨庫**（`Demo Tenant`；見下方 §6.3） |
| DD P0 Correctness Freeze | **已完成**（見 `docs/ENCLAVE_2_0_TECHNICAL_DD.md` §10.1） |
| DD P1 Architecture Convergence | **主幹完成**（見同 DD §10.2） |
| DD P2 Productization | **主幹完成**（compose overlays、Wiki 唯讀 UI、Graph API-only、Mobile experimental…） |
| 商業 GA 宣稱 | **未達**（缺外部滲透；法律／現場簽核屬人工） |
| 雲端來源 OAuth（SharePoint／Drive） | **本機階段 SKIP**（首發連接器為本機 NAS + BookStack） |
| 舊 README「Phase 13+ 生產就緒」 | **已作廢**；以下為現況真相 |

進度管制：`docs/OPEN_GATES.md` · `docs/PLAN_PROGRESS.md` · `docs/DEVELOPMENT_PLAN_TRIPLE_INJECTION.md`  
能力誠信邊界：`docs/CAPABILITY_CLAIMS.md`（**接線完成 ≠ 價值證明完成**）

---

## 1. 這是什麼／不是什麼

**是**

- 地端（on-prem / 本機 Docker）部署的企業 AI 知識平台
- **Control Plane**：租戶、部門、RBAC、稽核、文件生命週期、主知識索引（pgvector）
- 可選整合三個開源引擎為 sidecar，而不是把三套 UI 拼給客戶

**不是**

- 不是「已全面 GA、可對所有客戶宣稱零風險上線」
- 不是必須連 SharePoint／Google 才能進資料（本機資料夾／上傳即可）
- 不是把資料權威下放給 RAGFlow／PipesHub／WeKnora

---

## 2. 能力包（Product Packs）

| Pack | 環境開關 | 能力 | 本機現況 |
|------|----------|------|----------|
| **Enclave Base** | （永遠開） | 治理、上傳／NAS 進資料、解析管線、混合搜尋、聊天、稽核、備份腳本 | 核心可用 |
| **Document Intelligence** | `RAGFLOW_ENABLED=true` | DeepDoc／OCR／版面解析（RAGFlow）；**雲端 OCR 增強臂**（`CLOUD_OCR_PROVIDER`，預設關） | Pilot E2E 已驗證 `ragflow/deepdoc`；雲端臂見 §5.4 |
| **Enterprise Connect** | `PIPESHUB_ENABLED=true` | 企業來源同步與 ACL；**首發 `nas_smb`** | NAS 已認證；SP／Drive OAuth 本機 SKIP |
| **Knowledge Compiler** | `WEKNORA_ENABLED=true` | Wiki／Graph 編譯與引用（WeKnora） | Wiki 瀏覽＋**管理員編輯 UI** 已上線（`/knowledge/wiki`，編輯建新 revision）；編譯仍 API 觸發（管理員）；Graph 無產品 UI |
| **Agent Automation** | `AGENT_AUTOMATION_ENABLED` / `REVIEW_QUEUE_ENABLED` | 資料夾監控＋審核佇列（正式）；ReAct／MCP／Sandbox（experimental） | Watcher→Classifier→Review 已接線；工具型 Agent 不進預設導航 |

部署建議：

- **Lite** = 只開 Base（最小可演示）
- **Standard** = Base + 需要的 sidecar packs
- **Enterprise** = Standard + 觀測／HA 等（見 compose profiles）

---

## 3. 架構總覽

```text
┌─────────────────────────────────────────────────────────────┐
│  Web (React) / Mobile (Expo, experimental) / API Clients    │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  Enclave Control Plane (FastAPI + Celery + Beat)            │
│  · JWT / 部門 PEP / 稽核                                     │
│  · Knowledge Gateway (授權 fan-out + 聚合 + citation)       │
│  · Outbox → 投影到啟用中的 sidecar（失敗可重試，禁假收斂）   │
│  · Canonical Index: PostgreSQL + pgvector                   │
└───────┬───────────────────┬───────────────────┬─────────────┘
        │                   │                   │
   RAGFlow             PipesHub              WeKnora
   (解析/OCR)          (連接器/ACL)          (Wiki/Graph)
   可關閉               可關閉                可關閉
```

### 關鍵目錄

| 路徑 | 用途 |
|------|------|
| `app/main.py` / `app/api/` | API 入口與路由 |
| `app/gateway/` | Knowledge Gateway、adapters、授權邊界 |
| `app/services/` | 解析、檢索、connector、wiki、outbox… |
| `app/services/resource_policy.py` | 統一 Resource PEP |
| `app/services/retrieval_facade.py` | 統一 RetrievalFacade |
| `app/services/document_revocation.py` | 統一撤銷（tombstone + 資源級 deny） |
| `app/services/credential_vault.py` | Connector 憑證（`var/credentials/`，Fernet） |
| `app/tasks/` | Celery：文件處理、outbox、reconcile、connector poll |
| `app/agent/` | 資料夾監控／審核佇列（+ experimental 工具型 Agent） |
| `app/db/migrations/` | **唯一** Alembic migration 鏈 |
| `frontend/` | Web SPA（Vault Control IA） |
| `mobile/` | Expo App；**非 GA**（見 `mobile/EXPERIMENTAL.md`） |
| `compose/` | Compose overlays（見 `compose/README.md`） |
| `scripts/` | 評測、閘門、ops、`initial_data.py`、帳號腳本 |
| `docs/` | 計畫、ADR、runbook、UIUX、安全登記 |

### Compose（base 入口 + overlays）

| 檔案 | 用途 |
|------|------|
| `docker-compose.yml` | 本機開發最小堆疊（db:`5435`、redis:`6380`） |
| `docker-compose.profiles.yml` | lite / standard / enterprise |
| `docker-compose.prod.yml` | 生產硬化 |
| `compose/image-pins.env` | Sidecar image digest pins |
| `compose/pack-enabled.env` | Pack flag 與 sidecar 同開 |

本機 Lite：

```bash
docker compose -f docker-compose.profiles.yml --profile lite up -d
```

本機 Standard：

```bash
docker compose --env-file compose/image-pins.env --env-file compose/pack-enabled.env \
  -f docker-compose.profiles.yml --profile standard up -d
```

---

## 4. 資料怎麼進來（不必雲端）

| 方式 | 說明 | 狀態 |
|------|------|------|
| 網頁／API 上傳 | 一般文件進庫 | 可用 |
| 本機／NAS 資料夾 | `nas_smb` connector | **已認證** |
| SharePoint／Google Drive | 需雲端 OAuth | **本機階段跳過** |
| Agent 監控資料夾 | 掃描 → 審核 → 索引 | 可用 |

向量索引與文件同庫：**PostgreSQL + pgvector**（本機開發預設 `localhost:5435`，**不是**遠端 Linode，除非 `.env` 另行指向）。

---

## 5. 完成度稽核結論（2026-08-03）

### 5.1 已真正具備

- 多租戶文件管線、混合檢索、聊天 SSE、部門權限與 tombstone／撤權
- Outbox 投影、sidecar 可關、故障不假收斂
- UI 2.0：角色導覽、知識生命週期（來源→審核→入庫→引用→撤銷）、總覽待辦、**Wiki 瀏覽＋管理員編輯（revision 制）**
- NAS connector 認證、retrieval／security／module-disable 等 artifact PASS
- 三 sidecar 差異化能力逐項啟用並以消融閘門定價（見 §5.4）
- 嚴格進度閘門：`python scripts/plan_progress_gate.py --write-md --strict`

### 5.2 刻意未做／不可代勞

- 外部滲透測試
- 法律／模型商用授權審查
- 客戶現場 DR 簽核
- SharePoint／Drive OAuth（本機 SKIP）

### 5.3 產品完整度缺口

| 缺口 | 說明 |
|------|------|
| Wiki 編輯限管理員手動修訂 | 瀏覽全角色；管理員可在閱讀頁編輯（新增 revision 不覆寫歷史）；編譯仍由 WeKnora 觸發 |
| Graph **無生產寫入路徑與產品 UI** | 僅 tests/eval |
| Connector 表面過寬 | **真實認證僅 `nas_smb` + `bookstack`** |
| SSO | 程式存在但未掛入產品導航 |
| Mobile | experimental，無正式 CI |

### 5.4 能力啟用與價值證明（2026-08-03 閉環）

以 `docs/CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md` 逐項啟用三 sidecar 的差異化能力，並以消融閘門證明增量價值；誠信邊界見 `docs/CAPABILITY_CLAIMS.md`。

**已證明（PASS／MARGINAL 有證據）**

| 能力 | 閘門 | 結果 |
|------|------|------|
| DeepDoc 掃描件 OCR 啟用 | CV-RF-01a | PASS——掃描件由 0 字元轉為可檢索（CER 0.18–0.33 乾淨印刷子集） |
| 混合檢索（向量+關鍵詞） | CV-RF-02 | PASS——nDCG 0.933 vs 純向量 0.833，+12%（p=0.001） |
| 知識庫隔離 | CV-RF-03 | PASS——跨 KB 檢索為 0 |
| 階層切片 | CV-RF-04 | PASS——標題結構感知切片優於固定長度 |
| NAS 增量同步＋ACL | CV-PH-03 | PASS——新增／修改／刪除正確傳播，撤權即不可見 |
| Wiki 真實編譯＋引用 | CV-WK-03 | PASS——WeKnora 編譯出含 source_refs 頁面 |
| Wiki sole-source 撤權 | CV-WK-06 | PASS——來源撤權後 Wiki 頁對該使用者不可見（嚴格交集 ACL） |
| 引用 lineage（chunk→頁面 bbox） | B4 | PASS——DeepDoc bbox 串到引用定位 |

**已證明無增量價值（NO_VALUE，停用或維持預設關閉）**

| 能力 | 結論 |
|------|------|
| RAPTOR 階層摘要 | 對本語料無檢索增益，不啟用 |
| GraphRAG 圖譜檢索 | 對本語料問答無增益，維持 eval-only |
| Parent-child chunking | 無顯著增益 |
| 文件模板抽取 | 無增益 |

**掃描件 OCR 品質（CV-RF-01b，五臂消融定案）**

| 臂 | 66 欄嚴格命中 | 備註 |
|----|--------------|------|
| DeepDOC（地端預設） | 24.2% | 乾淨印刷掃描可用；手寫／拍照 CER 0.8+ |
| gpt-5.6-luna | 24.2%（Δ=0） | **手寫件輸出自信幻覺**，NO_VALUE |
| gpt-5.6-terra | 25.8% | INCONCLUSIVE |
| gemini-3-flash-preview | **30.3%** | 並列最佳；手寫切結書 4/4 全對 |
| mistral-ocr-latest（OCR 4） | **30.3%** | 並列最佳；最快（586s）、最便宜（$4/千頁）、含 typed blocks＋bbox |

結論：OCR 專精模型 > 通用模型；雲端臂仍未達 +20pp 全語料門檻（剩餘未命中屬真困難樣本）。**預設維持地端 DeepDOC**；雲端 OCR 已接為**選配增強臂**（`.env` 設 `CLOUD_OCR_PROVIDER=gemini|mistral|openai` + 對應 API key，僅在主解析產出過少時觸發，見 `app/services/cloud_ocr.py`）。

---

## 6. 快速啟動（本機）

### 6.1 本機開發埠（常見）

| 服務 | 位址 |
|------|------|
| API（uvicorn） | `http://127.0.0.1:8000` |
| Web（Vite） | `http://127.0.0.1:5173`（或以 `frontend/vite.config.ts` 預設 `3000`） |
| Postgres（Docker） | `localhost:5435` → 容器 `5432`，DB 名 `enclave` |
| Redis（Docker） | `localhost:6380` → 容器 `6379` |
| OpenAPI | `http://127.0.0.1:8000/docs` |

### 6.2 依賴 + API + 前端

```bash
cp .env.example .env
# 至少：SECRET_KEY、FIRST_SUPERUSER_*、POSTGRES_*、REDIS_*

# 依賴
docker compose up -d db redis

# Migration（空庫可從頭跑；正式鏈在 app/db/migrations）
python -m alembic upgrade head

# 種子：單一 Demo Tenant + superuser（email 來自 .env FIRST_SUPERUSER_EMAIL）
python scripts/initial_data.py

# Pilot 測試帳號（同租戶）
python scripts/ensure_ux_test_users.py

# API
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Worker（文件入庫需要）
python -m celery -A app.celery_app worker --loglevel=info --pool=solo

# Beat（outbox／reconcile；沒有則投影不收斂）
python -m celery -A app.celery_app beat --loglevel=info

# 前端
cd frontend && npm install && npm run dev -- --host 127.0.0.1 --port 5173
```

### 6.3 清空本機庫並重建單一租戶（Pilot 建議）

測試污染多租戶時，可重建乾淨 Pilot：

```bash
docker exec enclave-db-1 psql -U postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='enclave' AND pid<>pg_backend_pid();"
docker exec enclave-db-1 psql -U postgres -c "DROP DATABASE IF EXISTS enclave;"
docker exec enclave-db-1 psql -U postgres -c "CREATE DATABASE enclave OWNER postgres;"
docker exec enclave-db-1 psql -U postgres -d enclave -c "CREATE EXTENSION IF NOT EXISTS vector;"

python -m alembic upgrade head
python scripts/initial_data.py
python scripts/ensure_ux_test_users.py
docker exec enclave-redis-1 redis-cli FLUSHALL
```

之後知識庫為空，需重新上傳文件或接 NAS，問答才有證據。

### 6.4 Pilot 測試帳號（同 `Demo Tenant`）

| 帳號 | 密碼 | 角色 | 預設導覽 |
|------|------|------|----------|
| `admin@example.com` | `admin123` | owner（superuser） | 總覽｜問答｜知識｜治理｜系統 |
| `admin@enclave.local` | （`.env` `FIRST_SUPERUSER_PASSWORD`，預設 `admin123`） | owner | 同上 |
| `hr_test@enclave.local` | `hr123456` | hr | 問答｜知識｜我的用量 |
| `employee@example.com` | `employee123` | employee | 問答｜知識 |

### 6.5 Compose 一鍵 Lite／Standard／全堆疊

```bash
docker compose -f docker-compose.profiles.yml --profile lite up -d --build

docker compose --env-file compose/image-pins.env --env-file compose/pack-enabled.env \
  -f docker-compose.profiles.yml --profile standard up -d --build
```

**容器化全堆疊（最接近生產的本機驗證路徑）**：

```bash
docker compose up -d --build   # web:8001 + frontend:3001 + db + redis + worker + beat
docker compose ps              # 確認全部 healthy
```

瀏覽 `http://localhost:3001`（API 走 nginx 反代 `http://localhost:8001`）。首次啟動後如需 Wiki 演示資料：

```bash
docker compose exec web python scripts/seed_wiki_from_weknora.py
```

### 6.6 驗證

```bash
python scripts/plan_progress_gate.py --write-md --strict
python scripts/preflight_check.py --profile lite
python scripts/e2e_vertical_slice_full.py
python scripts/eval_retrieval_gate.py
python scripts/security_findings_gate.py
python scripts/certify_connector.py --type nas_smb
python scripts/ops_lifecycle.py backup

python -m pytest tests/ -q          # 後端全套（含 wiki 整合／雲端 OCR 管線）
cd frontend && npm test             # 前端 vitest（Wiki 列表／閱讀／編輯流程）
```

---

## 7. Web IA（角色導覽）

| 主選單 | 子頁 | 誰看得到 |
|--------|------|----------|
| **總覽** | `/overview` | owner／admin |
| **問答** | `/ask` | 全角色 |
| **知識** | 文件／**Wiki**／來源／審核／品質 | 文件、Wiki：可瀏覽知識；來源／審核：管理角色；品質：治理 |
| **治理** | 組織／部門／稽核／問答品質 | 治理角色 |
| **系統** | 能力包／健康／備份／部署 | 系統維運 |
| **創作** | `/create`（使用者選單，非主軸） | 有創作能力者 |
| **我的用量** | `/me/usage` | 依角色（如 HR） |

細節與文案原則見 `docs/UIUX_2_0_PLAN.md`、`frontend/README.md`。

---

## 8. 核心 API 面（摘要）

完整 OpenAPI：`http://127.0.0.1:8000/docs`

| 領域 | 前綴 | 備註 |
|------|------|------|
| 認證／使用者 | `/api/v1/auth`, `/users` | 登入：`POST /auth/login/access-token` |
| 文件 | `/documents` | 預設 `limit=100`；前端以分頁累加 |
| 知識維護 | `/kb-maintenance` | 健康、缺口、分類、備份、integrity |
| 聊天／生成 | `/chat`, `/generate` | |
| Knowledge Gateway | `/gateway` | |
| Connectors | `/connectors` | 首發 NAS |
| Wiki／Graph | `/wiki`, `/graph` | Wiki 唯讀 UI 已上線；Graph API-only |
| Agent／審核 | `/agent`, `/agent-approvals` | |
| 公司／組織 | `/company`, `/organization` | |
| 維運／稽核 | `/operations`, `/admin`, `/audit` | |

---

## 9. 前端與行動端

**Web（`frontend/`）**  
React 19 + Vite + Tailwind 4：Vault Control IA（總覽／問答／知識／治理／系統），知識含 Wiki 瀏覽與管理員編輯。單元測試：vitest + testing-library（`npm test`）。詳見 `frontend/README.md`。

**Mobile（`mobile/`）**  
Expo 子集；**非 2.0 GA 路徑**——見 `mobile/README.md`、`mobile/EXPERIMENTAL.md`。

---

## 10. 相關文件

| 文件 | 內容 |
|------|------|
| `docs/UIUX_2_0_PLAN.md` | UI/UX 規劃書 |
| `docs/CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md` | 能力啟用與價值證明計畫（消融閘門結果） |
| `docs/CAPABILITY_CLAIMS.md` | 能力宣稱誠信邊界（可宣稱／不可宣稱） |
| `docs/ENCLAVE_2_0_TECHNICAL_DD.md` | 技術 Due Diligence |
| `docs/DEVELOPMENT_PLAN_TRIPLE_INJECTION.md` | 主計畫與出口條件 |
| `docs/OPEN_GATES.md` | 開放／SKIP 閘門 |
| `docs/PLAN_PROGRESS.md` | 自動進度看板 |
| `compose/README.md` | Compose overlays |
| `frontend/README.md` | Web 路由與開發 |
| `docs/adr/` | 架構決策記錄 |
| `docs/runbooks/` | Pilot／Connector runbook |
| `docs/security/FINDINGS_REGISTER.md` | 安全發現登記 |
| `artifacts/*_last_run.json` | 自動化驗收證據 |

---

## 11. 版本敘事

| 稱呼 | 含義 |
|------|------|
| Enclave 1.x（歷史） | 單一知識庫／聊天／生成／Agent 監控 |
| **Enclave 2.0（現況）** | Control Plane + Triple Injection；UI 2.0 IA（含 Wiki 唯讀瀏覽）；本機核心與能力價值證明已閉環 |
| Enclave GA（未來） | 2.0 + 外部滲透關閉 + 法律／現場簽核 +（可選）雲端 connector |

---

## 授權與商用聲明

程式授權見倉庫 `LICENSE`／NOTICE。  
**模型權重、第三方 SaaS、開源依賴的商用條款需另行法律審查**——本 README 不做合規保證。
