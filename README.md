# Enclave — 企業知識 Control Plane ＋ MKA 製造業知識助理

> 客戶只面對**一套**身分、權限、知識庫生命週期、問答與維運。
> 高品質解析、企業來源同步、知識編譯以**可開關的 sidecar 能力包**接入；資料權威與最終授權留在 Enclave。
> **MKA（Manufacturing Knowledge Assistant）**是長在 Control Plane 上的第一個垂直產品：讓製造業每個職務的人用講話、掃碼、打字把知識放進來、取出來——**每句回答有出處、每次寫入有簽核、與 SOP 的矛盾會被攔下**。

| 項目 | 狀態（2026-08-06） |
|------|-------------------------|
| 產品線 | **Enclave 平台**（Triple Injection：RAGFlow + PipesHub + WeKnora）＋ **MKA 製造業垂直層** |
| **生產環境** | **已上線：https://kachu.tw**（Linode 8GB 大阪，HTTPS＋自動續期，10 容器全健康；見 `docs/LINODE_MIGRATION_ASSESSMENT.md`） |
| MKA 願景平台 | **28/28 閘門通過**；三劇本程式化 E2E **26/26**（本機＋生產各跑過一輪） |
| AI 問答品質（Point A→B） | 主集 128/128、對抗 8/8；**hold-out 盲測 Z3 67/85、Z4 39/50（未見文件約 78–79%）**；Point B「敢亂問」**未達標**（見 `docs/VISION_POINT_A_TO_B.md`、`docs/STAGE_SUMMARY_2026-08-05.md`） |
| 流程強弱地圖 | `docs/PIPELINE_STRENGTH_MAP.md`（逐環節評級＋證據＋宣稱邊界） |
| 能力啟用與價值證明 | 已閉環（消融閘門定價；見 `docs/CAPABILITY_CLAIMS.md`——**接線完成 ≠ 價值證明完成**） |
| 商業 GA 宣稱 | **未達**（缺外部滲透；法律／現場簽核屬人工；生產 PoC 關閉 ClamAV） |
| 雲端化 | Phase 1 落地：StorageBackend 雙實作、租戶 RLS shadow（27 表）、SSO/MFA/配額/計費程式層完成 |
| 雲端來源 OAuth（SharePoint／Drive） | 本機階段 SKIP（首發連接器為本機 NAS + BookStack） |

進度管制：`docs/OPEN_GATES.md` · `docs/PLAN_PROGRESS.md` · `docs/DEVELOPMENT_PLAN_TRIPLE_INJECTION.md`

---

## 1. 這是什麼／不是什麼

**是**

- 企業 AI 知識 **Control Plane**：租戶、部門、RBAC、稽核、文件生命週期、主知識索引（pgvector）
- **MKA 製造業知識助理**：職務即入口的工作台、語音開單、掃碼進場景、表單簽核、師傅知識卡生命週期、SOP 衝突攔截（見 §2）
- 可選整合三個開源引擎為 sidecar，而不是把三套 UI 拼給客戶
- **三種販售形態**（同一套程式碼，見 `docs/CLOUD_AND_COMMERCIALIZATION_PLAN.md`）：

| 形態 | 說明 | 現況 |
|------|------|------|
| **A 地端自管** | 客戶 Compose／air-gap | 本機 Pilot 主路徑 |
| **B 託管私有雲** | 每客獨立實例 | **kachu.tw 即為首個實例**（已上線） |
| **C 多租戶 SaaS** | 共享控制面＋RLS | Phase 2（shadow RLS 已落地） |

**不是**

- 不是「已全面 GA、可對所有客戶宣稱零風險上線」
- 不是必須連 SharePoint／Google 才能進資料（本機資料夾／上傳即可）
- 不是把資料權威下放給 RAGFlow／PipesHub／WeKnora
- 不是「亂丟亂問都穩」——未見文件答題 78–79%，重要決策仍須人工核對

---

## 2. MKA 製造業知識助理（首個垂直產品）

**解決的問題**：知識在老師傅腦袋裡、規格在業務的 Excel 裡、SOP 在沒人翻的文件櫃裡。

### 2.1 核心能力

| 能力 | 說明 |
|------|------|
| **職務即入口** | 登入後依「租戶＋職能＋部門」動態生成工作台；5 個正式職能模組（規格SOP／報價／異常交接／品質8D／訓練傳承）DB 路由，非 prompt 假裝 |
| **語音輸入** | OpenAI STT/TTS；語音開報價單、語音異常回報，關鍵欄位標「需確認」不硬猜 |
| **掃碼進場景** | SceneRegistry 把 opaque QR token 解析成設備場景；之後的問答與表單**自動限定該設備**並預填欄位；未註冊 QR fail-closed |
| **表單＋簽核** | 報價單／異常報告／交接班：建單→驗證→計算→送審→核准→匯出；樂觀鎖、idempotency、不可變快照 |
| **公司版型** | 上傳公司自己的 DOCX/XLSX 版型，`{{placeholder}}` 映射，匯出即正式文件 |
| **師傅知識卡** | 訪談模式：口述→系統抽出步驟/注意事項→草稿；**核准後新人才查得到**（草稿隔離） |
| **SOP 衝突攔截** | 知識卡送審時與正式 SOP 比對，矛盾（如老做法違反現行禁令）**攔下並攤開**，人工處置後才放行 |
| **企業寫入護欄** | ERP/CRM/MES adapter fail-closed；DB 化 write guardrail（最小權限、冪等、核准 token、可回滾） |

### 2.2 線上體驗（生產環境）

- 入口：**https://kachu.tw**
- 測試帳號：`sales / field / master / newcomer / viewer @demo.mka`（密碼統一 `Demo12345`），管理員帳號見主機 `/opt/enclave/.env.production`
- ** DEMO 劇本**：`docs/MKA_DEMO_QUESTION_SET.md`（**有 PDF 版**；開場白、逐字問題、預期畫面、救場備案，拿到就能上台）
- 完整測試劇本：`docs/MKA_UX_TEST_SCRIPTS.md`（有 PDF 版；三劇本＋UIUX 觀察點＋權限邊界）
- 功能驗收矩陣：`docs/MKA_FEATURE_INVENTORY.md` §9

---

## 3. 能力包（Product Packs）

| Pack | 環境開關 | 能力 | 現況 |
|------|----------|------|------|
| **Enclave Base** | （永遠開） | 治理、上傳／NAS 進資料、解析管線、混合搜尋、聊天、稽核、備份腳本 | 核心可用 |
| **MKA** | `FIXED_FORM_ENABLED`／`KNOWHOW_CARD_ENABLED`／`MODULE_ROUTER_ENABLED`／`VOICE_STT_ENABLED`／`VOICE_TTS_ENABLED` | §2 全部 | 生產已啟用 |
| **Document Intelligence** | `RAGFLOW_ENABLED=true` | DeepDoc／OCR／版面解析；雲端 OCR 增強臂（預設關） | Pilot E2E 已驗證；生產 PoC 關閉（8GB RAM 取捨） |
| **Enterprise Connect** | `PIPESHUB_ENABLED=true` | 企業來源同步與 ACL；首發 `nas_smb` | NAS 已認證；SP／Drive OAuth 本機 SKIP |
| **Knowledge Compiler** | `WEKNORA_ENABLED=true` | Wiki／Graph 編譯與引用 | Wiki 瀏覽＋管理員編輯 UI 已上線；Graph 無產品 UI |
| **Agent Automation** | `AGENT_AUTOMATION_ENABLED` / `REVIEW_QUEUE_ENABLED` | 資料夾監控＋審核佇列（正式）；ReAct／MCP／Sandbox（experimental） | Watcher→Classifier→Review 已接線 |

部署建議：**Lite**＝只開 Base · **Standard**＝Base＋需要的 sidecar packs · **Enterprise**＝Standard＋觀測／HA（見 compose profiles）

---

## 4. 架構總覽

```text
┌─────────────────────────────────────────────────────────────┐
│  Web (React) / Mobile (Expo, experimental) / API Clients    │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  Enclave Control Plane (FastAPI + Celery + Beat)            │
│  · JWT / 部門 PEP / 稽核 / 配額 / 計費                       │
│  · MKA：模組路由、場景、表單、知識卡、衝突檢查、審核          │
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
| `app/services/` | 解析、檢索、connector、wiki、outbox、**MKA 服務群**（`mka_persistence`／`module_router`／`sop_conflict`／`write_guardrail`／`form_template_service`…） |
| `app/services/retrieval_facade.py` | 統一 RetrievalFacade |
| `app/services/source_verifier.py` | Source-grounded 逐字溯源稽核（見 §6.5） |
| `app/models/mka.py` | MKA 領域模型（場景／職能／表單／知識卡／審核／事件） |
| `app/tasks/` | Celery：文件處理、outbox、reconcile、connector poll |
| `app/db/migrations/` | **唯一** Alembic migration 鏈 |
| `frontend/` | Web SPA（Vault Control IA＋MKA 職能頁面） |
| `mobile/` | Expo App；**非 GA**（見 `mobile/EXPERIMENTAL.md`） |
| `compose/` | Compose overlays（見 `compose/README.md`） |
| `scripts/` | 評測、閘門、ops、`initial_data.py`、部署（`deploy_linode.sh`） |
| `test-materials/` | MKA 測試語料、版型、語音腳本、E2E 腳組（見其 README） |
| `docs/` | 計畫、ADR、runbook、UIUX、安全登記、**DEMO 劇本** |

---

## 5. 資料怎麼進來（不必雲端）

| 方式 | 說明 | 狀態 |
|------|------|------|
| 網頁／API 上傳 | 一般文件進庫 | 可用 |
| 本機／NAS 資料夾 | `nas_smb` connector | **已認證** |
| SharePoint／Google Drive | 需雲端 OAuth | **本機階段跳過** |
| Agent 監控資料夾 | 掃描 → 審核 → 索引 | 可用 |

向量索引與文件同庫：**PostgreSQL + pgvector**（本機開發預設 `localhost:5435`；生產見 `docker-compose.prod.yml`）。

---

## 6. 完成度稽核（2026-08-06 更新）

### 6.1 已真正具備

- 多租戶文件管線、混合檢索、聊天 SSE、部門權限與 tombstone／撤權
- Outbox 投影、sidecar 可關、故障不假收斂
- UI 2.0：角色導覽、知識生命週期、Wiki 瀏覽＋管理員編輯（revision 制）
- **MKA 全鏈路**：§2 所列能力皆有程式化 E2E 證據（26/26，本機＋生產）
- NAS connector 認證、retrieval／security／module-disable 等 artifact PASS
- 雲端化 Phase 1：StorageBackend、RLS shadow、SSO/MFA、配額、NewebPay 計費（程式層）
- 嚴格進度閘門：`plan_progress_gate.py --strict`（47/48，唯一缺外部滲透）、`mka_progress_gate.py --all`（28/28）

### 6.2 刻意未做／不可代勞

- 外部滲透測試（商業 GA 唯一未勾出口）
- 法律／模型商用授權審查、客戶現場 DR 簽核
- 真實客戶 DOCX/XLSX 版型比對、ERP/MES 真實整合、真人 UX 研究、真機弱網噪音測試
- SharePoint／Drive OAuth（本機 SKIP）

### 6.3 已知弱點（誠實清單）

逐環節評級與證據見 **`docs/PIPELINE_STRENGTH_MAP.md`**。摘要：

- 未見文件答題 **78–79%**（Z3/Z4 凍結基線）——找錯檔、金額漏招、跨庫干擾為主要失分類
- 掃描版 PDF 生產不支援（LlamaParse 關閉）；生產 ClamAV 關閉（RAM 取捨）
- 語音在工廠噪音、中英夾雜料號情境未測
- 單機單點無 HA；BM25 索引全量記憶體，大庫效能未驗證
- MKA 工作流僅經自製語料驗證，無 hold-out 盲測證據（Z5 待做）

### 6.4 能力啟用與價值證明（2026-08-03 閉環）

以消融閘門逐項證明 sidecar 差異化能力的增量價值；誠信邊界見 `docs/CAPABILITY_CLAIMS.md`。

**已證明（PASS 有證據）**

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

**已證明無增量價值（NO_VALUE，停用或維持預設關閉）**：RAPTOR 階層摘要、GraphRAG 圖譜檢索、Parent-child chunking、文件模板抽取。

**掃描件 OCR 品質（CV-RF-01b，五臂消融定案）**：地端 DeepDOC 24.2% 嚴格命中為預設；gemini-3-flash-preview 與 mistral-ocr-latest 並列最佳（30.3%）但未達 +20pp 全語料門檻；雲端 OCR 已接為**選配增強臂**（`CLOUD_OCR_PROVIDER`，僅主解析產出過少時觸發）。

### 6.5 AI 問答品質架構（Point A→B 路線）

目標：問答的正確性、穩定性、可解釋性由**架構**撐住，不靠 prompt 或運氣。總綱見 `docs/VISION_POINT_A_TO_B.md`。

**驗收數字（誠實版）**

| 題庫 | 結果 | 性質 |
|------|------|------|
| 主黃金集（40＋展開 88＝128 題） | 128/128 | 開發集 |
| 盲測 Z2（8 份未見文件 × 27 題） | 27/27 | 小樣本，**不得單獨當 Point B** |
| **盲測 Z3（55 檔 hold-out × 85 題）** | **67 pass／3 fail／15 review** | 凍結基線 |
| **盲測 Z4（40 檔全新 hold-out × 50 題）** | **39 pass／5 fail／6 review**；拒答 D 類 6/6 | 凍結基線，排除 Z2/Z3 用過檔名與高頻客戶 |
| 對抗集（誘騙／庫外／未來事實） | 8/8 PASS | — |

**白話**：未見文件約 78–79%；內部示範與試用可以，「隨便丟隨便問都穩」還不行。修洞後禁止重跑 Z3/Z4 主集當證明——須以新 hold-out（Z5）驗證泛化。

**問答管線架構層**（`app/services/`）

| 層 | 模組 | 作用 |
|----|------|------|
| 意圖規劃 | `query_planner` / `tool_router` / `multi_step_orchestrator` | QueryPlan 六類意圖驅動多臂檢索；檔名導向 scoped 檢索＋document head 不變式 |
| 檢索融合 | `retrieval_facade` / gateway fusion | 文件／Wiki／Graph／Connector 統一入口；上下文組裝含跨文件多樣性保護（2026-08-06 修復） |
| 拒答紀律 | 結構化 refusal（`refusal` in retrieval ctx） | 不可答題強制拒答，不讓 LLM 胡謅 |
| **逐字溯源稽核** | `source_verifier.py` | 生成後稽核：每條論點須附逐字 `source_quote`，程式化子字串比對；`derived` 型別涵蓋換算／摘要 |

**Source-grounded 稽核層開關**（`.env`）：`SOURCE_VERIFY_MODE=off|shadow|enforce`（目前常駐 shadow：131 次稽核 0 故障、strict 逐字通過率 74.8%、未通過抽樣 0 條真幻覺；enforce 待更多數據排除 OCR 雜訊假陽性）。

**誠信邊界**：稽核層保證「回答忠實於檢索到的證據」；「檢索到對的證據」由意圖規劃／scoped 檢索／交付閘門負責——兩道牆互補，不互相替代。

---

## 7. 部署

### 7.1 生產（Linode 實績）

- **https://kachu.tw** — Linode 8GB／4 vCPU／大阪；Docker Compose（`docker-compose.prod.yml`）10 容器：web／worker／worker-beat／db／redis／gateway(nginx)／frontend／ollama-embed／prometheus／grafana
- HTTPS：Let's Encrypt（certbot，自動續期 hooks 已設）
- 一鍵部署腳本：`scripts/deploy_linode.sh`；驗證腳本：`scripts/verify_deployment.sh`
- 完整評估、上線實績與取捨：`docs/LINODE_MIGRATION_ASSESSMENT.md`

### 7.2 本機 Compose

```bash
# Lite（最小可演示）
docker compose -f docker-compose.profiles.yml --profile lite up -d

# Standard（含 sidecar packs）
docker compose --env-file compose/image-pins.env --env-file compose/pack-enabled.env \
  -f docker-compose.profiles.yml --profile standard up -d

# 全堆疊（最接近生產的本機驗證路徑）：web:8001 + frontend:3001
docker compose up -d --build
```

---

## 8. 快速啟動（本機開發）

### 8.1 本機開發埠（常見）

| 服務 | 位址 |
|------|------|
| API（uvicorn） | `http://127.0.0.1:8000`（MKA 實測期間用 `:8005`） |
| Web（Vite） | `http://127.0.0.1:5173`（或 `frontend/vite.config.ts` 預設 `3000`） |
| Postgres（Docker） | `localhost:5435` → 容器 `5432`，DB 名 `enclave` |
| Redis（Docker） | `localhost:6380` → 容器 `6379` |
| OpenAPI | `http://127.0.0.1:8000/api/v1/openapi.json`（`/docs` 生產關閉） |

### 8.2 依賴 + API + 前端

```bash
cp .env.example .env
# 至少：SECRET_KEY、FIRST_SUPERUSER_*、POSTGRES_*、REDIS_*

docker compose up -d db redis
python -m alembic upgrade head
python scripts/initial_data.py          # 單一 Demo Tenant + superuser
python scripts/ensure_ux_test_users.py  # Pilot 測試帳號

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
python -m celery -A app.celery_app worker --loglevel=info --pool=solo
python -m celery -A app.celery_app beat --loglevel=info
cd frontend && npm install && npm run dev -- --host 127.0.0.1 --port 5173
```

### 8.3 清空本機庫並重建單一租戶（Pilot 建議）

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

### 8.4 測試帳號

**平台 Pilot 帳號（本機 `Demo Tenant`）**

| 帳號 | 密碼 | 角色 |
|------|------|------|
| `admin@example.com` | `admin123` | owner（superuser） |
| `hr_test@enclave.local` | `hr123456` | hr |
| `employee@example.com` | `employee123` | employee |

**MKA 演示帳號（本機與生產 kachu.tw 通用）**

| 帳號 | 密碼 | 職能 | 對應劇本 |
|------|------|------|----------|
| `sales@demo.mka` | `Demo12345` | 業務 | 劇本 A |
| `field@demo.mka` | `Demo12345` | 設備 | 劇本 B |
| `master@demo.mka` | `Demo12345` | 班長（師傅） | 劇本 C |
| `newcomer@demo.mka` | `Demo12345` | 新人 | 劇本 C 後段 |
| `viewer@demo.mka` | `Demo12345` | 唯讀 | 權限邊界 |

建立方式：`python test-materials/e2e/setup_test_env.py`（細節見 `test-materials/README.md`）。

### 8.5 驗證

```bash
python scripts/plan_progress_gate.py --write-md --strict   # 主計畫閘門
python scripts/mka_progress_gate.py --all                  # MKA 閘門（28 項）
python scripts/preflight_check.py --profile lite
python scripts/e2e_vertical_slice_full.py
python scripts/eval_retrieval_gate.py
python scripts/security_findings_gate.py
python scripts/certify_connector.py --type nas_smb
python scripts/ops_lifecycle.py backup

# MKA 三劇本程式化 E2E（需先 setup＋入庫，見 test-materials/README.md）
python test-materials/e2e/setup_test_env.py
python test-materials/e2e/ingest_docs.py
python test-materials/e2e/e2e_walkthrough.py

python -m pytest tests/ -q          # 後端全套
cd frontend && npm test             # 前端 vitest
```

---

## 9. Web IA（角色導覽）

| 主選單 | 子頁 | 誰看得到 |
|--------|------|----------|
| **工作台** | `/job`（職務動態生成） | 全角色（依職能不同） |
| **問答** | `/ask` | 全角色 |
| **知識** | 文件／Wiki／來源／審核／品質 | 文件、Wiki：可瀏覽知識；來源／審核：管理角色 |
| **表單** | `/forms/mine`、`/forms/:formKey` | 依職能模組 |
| **知識卡** | `/knowhow`、`/knowhow/interview` | 依職能模組 |
| **審核中心** | `/approvals` | 管理角色 |
| **治理** | 組織／部門／稽核／問答品質 | 治理角色 |
| **系統** | 能力包／模組／健康／備份／部署 | 系統維運 |
| **我的用量** | `/me/usage` | 依角色 |

細節見 `docs/UIUX_2_0_PLAN.md`、`frontend/README.md`。

---

## 10. 核心 API 面（摘要）

完整 OpenAPI：`/api/v1/openapi.json`

| 領域 | 前綴 | 備註 |
|------|------|------|
| 認證／使用者 | `/api/v1/auth`, `/users` | 登入：`POST /auth/login/access-token` |
| 文件 | `/documents` | 預設 `limit=100`；前端以分頁累加 |
| 聊天／生成 | `/chat`, `/generate` | SSE 串流；支援 `module_key`＋`scene_context` |
| **MKA** | `/job-modules`, `/job-roles`, `/scene/registry`, `/forms`, `/knowhow`, `/interview`, `/approvals`, `/form-templates`, `/enterprise`, `/mka-metrics` | 見 `docs/MKA_FEATURE_INVENTORY.md` |
| Knowledge Gateway | `/gateway` | |
| Connectors | `/connectors` | 首發 NAS |
| Wiki／Graph | `/wiki`, `/graph` | Wiki UI 已上線；Graph API-only |
| 知識維護 | `/kb-maintenance` | 健康、缺口、分類、備份、integrity |
| 公司／組織 | `/company`, `/organization` | |
| 維運／稽核 | `/operations`, `/admin`, `/audit` | |

---

## 11. 前端與行動端

**Web（`frontend/`）**
React 19 + Vite + Tailwind 4：Vault Control IA＋MKA 職能頁面（動態工作台、表單、知識卡、訪談、審核）。單元測試：vitest（`npm test`）。

**Mobile（`mobile/`）**
Expo 子集；**非 GA 路徑**——見 `mobile/README.md`、`mobile/EXPERIMENTAL.md`。

---

## 12. 相關文件

| 文件 | 內容 |
|------|------|
| **`docs/MKA_DEMO_QUESTION_SET.md`** | **對外 DEMO 表演劇本（有 PDF）** |
| `docs/MKA_UX_TEST_SCRIPTS.md` | MKA 三劇本完整測試腳本（有 PDF） |
| `docs/MKA_FEATURE_INVENTORY.md` | MKA 功能驗收矩陣 |
| **`docs/PIPELINE_STRENGTH_MAP.md`** | **整條流程逐環節強弱地圖（活文件）** |
| `docs/LINODE_MIGRATION_ASSESSMENT.md` | 雲端化評估＋Linode 上線實績 |
| `docs/STAGE_SUMMARY_2026-08-05.md` | 階段總結（Z3/Z4 盲測證據與宣稱邊界） |
| `docs/VISION_POINT_A_TO_B.md` | AI 問答品質願景路線 |
| `docs/CAPABILITY_CLAIMS.md` | 能力宣稱誠信邊界 |
| `docs/CLOUD_AND_COMMERCIALIZATION_PLAN.md` | 雲端化與商業產品化計畫 |
| `docs/ENCLAVE_2_0_TECHNICAL_DD.md` | 技術 Due Diligence |
| `docs/OPEN_GATES.md` | 開放／SKIP 閘門 |
| `docs/PLAN_PROGRESS.md` | 自動進度看板 |
| `test-materials/README.md` | MKA 測試語料總表與環境操作 |
| `compose/README.md` | Compose overlays |
| `frontend/README.md` | Web 路由與開發 |
| `docs/adr/` | 架構決策記錄 |
| `docs/runbooks/` | Pilot／Connector／託管私有雲 runbook |
| `docs/security/FINDINGS_REGISTER.md` | 安全發現登記 |
| `artifacts/*_last_run.json` | 自動化驗收證據 |

---

## 13. 版本敘事

| 稱呼 | 含義 |
|------|------|
| Enclave 1.x（歷史） | 單一知識庫／聊天／生成／Agent 監控 |
| Enclave 2.0 | Control Plane + Triple Injection；UI 2.0 IA；能力價值證明閉環；問答品質架構上線 |
| **Enclave 2.0 + MKA（現況）** | 2.0 之上長出第一個垂直產品：製造業知識助理（職能工作台／語音／掃碼／表單簽核／知識卡／SOP 衝突攔截）；**首個託管實例 kachu.tw 上線**；hold-out 盲測 78–79%，Point B 未達標 |
| Enclave GA（未來） | 現況 + 外部滲透關閉 + 法律／現場簽核 + Z5 泛化驗證 +（可選）雲端 connector |
| Enclave Cloud（路線） | 託管私有雲 → 多租戶 SaaS；見 `docs/CLOUD_AND_COMMERCIALIZATION_PLAN.md` |

---

## 授權與商用聲明

程式授權見倉庫 `LICENSE`／NOTICE。
**模型權重、第三方 SaaS、開源依賴的商用條款需另行法律審查**——本 README 不做合規保證。
