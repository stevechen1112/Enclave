# Enclave 雲端化與商業產品化完整計畫

**文件版本**：1.1  
**建立日期**：2026-08-04  
**定位**：中長期路線總綱（雲端化 × 商業產品化 × 營運就緒）  
**狀態**：✅ **Accepted（2026-08-04，D1–D7 全部定案）**——同步修訂 ADR-003 v2；進度以 §11.2 閘門為唯一語言

**關聯文件**

| 文件 | 關係 |
|------|------|
| `docs/adr/ADR-003-onprem-saas-boundary.md` | 現行邊界：首發單客戶地端；本計畫提案**擴張**該邊界（非推翻地端優先） |
| `docs/VISION_POINT_A_TO_B.md` | AI 問答品質架構（雲端化時必須原樣保留） |
| `docs/CAPABILITY_CLAIMS.md` / `CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md` | 能力誠信；接線 ≠ 可宣稱 |
| `docs/OPEN_GATES.md` / `docs/ENCLAVE_2_0_TECHNICAL_DD.md` | 商業 GA 人工閘門（滲透／法律／DR） |
| `docs/DEVELOPMENT_PLAN_TRIPLE_INJECTION.md` | Control Plane 主計畫 |
| UniHR（`Desktop/aihr`）對應文件 | 成熟 SaaS 參照（見 §2） |

---

## 0. 一句話目標

把 Enclave 從「**地端單客戶 Control Plane＋混合雲智慧**」演進為可同時支援三種販售形態的產品平台——**託管私有雲、多租戶 SaaS、客戶自管地端**——且雲端化後的問答正確性、隔離強度、營運可觀測性**不低於**現有地端閉環與 UniHR 已證明的商業殼層水準。

---

## 1. 現況真相（2026-08-04 證據）

### 1.1 Enclave 今天實際是什麼

| 平面 | 現況 | 證據 |
|------|------|------|
| 部署意圖 | 單客戶地端（Compose）；本機 Pilot 單一 Demo Tenant | ADR-003；`README.md` §6.3 |
| 資料平面 | PostgreSQL + pgvector、Redis、本機 `UPLOAD_DIR` | `app/config.py`；`docker-compose*.yml` |
| 應用多租戶 | `tenant_id` 全覆蓋 + Resource PEP + 部門 ACL | `resource_policy.py`；ADR-003／004 |
| DB 硬隔離 | **無 PostgreSQL RLS** | ADR-003 明文；全庫無 `ENABLE ROW LEVEL SECURITY` |
| 物件儲存 | **本機 volume**；MinIO 僅 enterprise compose 服務、app 無 S3 client | `documents.py`；`compose/enterprise.yml` |
| 主 LLM / Rerank / 雲端 OCR | **已在雲端 API**（Luna／Voyage／選配 OCR；Sol 已退場、Terra 備用） | `deployment_mode.py`；`cloud_ocr.py` |
| 內部模型 | 本地 Ollama（稽核／embedding／scan） | `SOURCE_VERIFY_MODEL`；profiles |
| 配額骨架 | `PLAN_QUOTAS` + `check_quota` + `UsageRecord` | `schemas/tenant.py`；`crud_tenant.py` |
| 金流／自助註冊／email 驗證 | **無**（ADR-003 明確不做） | ADR-003 |
| SSO | 程式 skeleton、**未掛 router** | `sso.py`；`api.py` 未 include |
| 觀測 | Prometheus + Grafana（prod compose）；**無 Sentry／無 app 內 Langfuse** | `middleware/metrics.py`；`monitoring/` |
| Sidecar | 部署級單一 dataset／KB／org——適合每客戶一套，**不適共享多租戶** | `RAGFLOW_DATASET_ID`；`WEKNORA_KB_ID` |
| AI 問答品質 | 主集 128/128、盲測 27/27、逐字溯源 shadow | `VISION_POINT_A_TO_B.md` §5.5 |
| 商業 GA | **No-Go**（滲透／法律／DR 未關） | DD；`OPEN_GATES.md` |

**白話**：今天的 Enclave 是「資料與治理在地、智慧呼叫可走雲」的混合體；多租戶**資料模型預留了**，但**商業殼層與雲端基礎設施殼層尚未產品化**。

### 1.2 為什麼現在寫這份計畫

1. Point A→B 問答品質架構已接近可對外展示（~90%），下一層瓶頸轉為**產品形態與交付形態**。  
2. UniHR 已是同系譜的多租戶 B2B SaaS 實戰參照——對考證明兩邊強弱互補，應系統性吸收其商業殼層，而非各自重複踩坑。  
3. ADR-003「明確不做 SaaS 計費／試用」是**首發優先級決策**，不是永久禁令；本計畫定義何時、如何、分幾階段擴張該邊界。

---

## 2. UniHR 參照盤點（可移植 vs 必須重做）

> 路徑基準：`C:\Users\User\Desktop\aihr`。以下僅列有檔案證據的能力。

### 2.1 UniHR 已證明、Enclave 應吸收的商業殼層

| 能力域 | UniHR 證據 | Enclave 現況 | 移植策略 |
|--------|------------|--------------|----------|
| **PG RLS** | `alembic/.../t8_1_tenant_rls.py`；`apply_rls_context`；`RLS_ENFORCEMENT_ENABLED` | 僅應用層 WHERE + PEP | **直接移植模式**：分階段 rollout＋bypass 角色（見 §5.2） |
| **物件儲存 R2** | `boto3` → Cloudflare R2；key=`{tenant_id}/{doc_id}` | 本機 UPLOAD | **抽象 StorageBackend**（local／S3／R2），預設切 R2 或 Linode Object Storage |
| **方案配額強制** | `subscription.py` PLAN_MATRIX；`quota_enforcement` → 429 | 有骨架、強度不足 | 對齊 matrix＋Depends 強制；補 token／文件／使用者三軸 |
| **金流** | NewebPay 權威；Stripe webhook **封存未掛** | 無 | 台灣市場先 NewebPay；國際再 Stripe（勿重蹈「半套 Stripe」） |
| **Auth 硬化** | Cookie+CSRF、email verify、SSO、Admin MFA | JWT＋invite；SSO 未掛；無 email verify／MFA 執行 | 掛載 SSO；加 verify／MFA；Cookie 模式可選 |
| **上傳掃毒** | ClamAV fail-closed（prod compose） | 無 | prod／SaaS 必開；地端可選 |
| **觀測三件套** | Sentry + Langfuse + `/metrics` | 僅 Prometheus／Grafana | 接 Sentry＋Langfuse（問答 trace 對齊 source_verification） |
| **Onboarding** | Sales-Led 開戶 + Day0/1/3 drip + wizard | invite only | **採用 Sales-Led 為主**；自助註冊為 Phase 後段選配 |
| **向量雙路徑** | Pinecone namespace + pgvector failover | 僅 pgvector（優勢：資料主權） | SaaS 可選 Pinecone／Qdrant Cloud；地端維持 pgvector；**寫入真相永遠在 PG** |
| **多區域模板** | `docker-compose.region.yml`；`MULTI_REGION.md` | 無 | 中期引入「資料駐留區域」選項（合規驅動） |
| **生產 SOP** | `PRODUCTION_DEPLOY_SOP.md`；backup drill；DPA | ops_lifecycle 有、DR 簽核未關 | 吸收 SOP／DPA／刪除權流程 |

### 2.2 UniHR 的成熟度邊界（勿盲目複製）

| 邊界 | 證據 | Enclave 決策 |
|------|------|--------------|
| GTM 定位是 **Sales-Led／Design Partner**，非純自助公開販售 | `SALES_LED_ONBOARDING_MODEL.md`；`GO_TO_MARKET_READINESS_*` | **同期採納**：首 12 個月雲端版同樣 Sales-Led |
| 部署是 **Compose on VPS**，無 K8s | 全庫無 helm／k8s | Phase 1–2 同採 Compose／託管 VM；Phase 3 再評估 K8s |
| 跨部門 ACL 在 chat 檢索曾有破洞（對考實測） | `EVAL_2026-08-04_BLIND_TEST_AND_FIX_PLAN.md` | Enclave 以 PEP＋scoped 檢索為準；雲端化時強制 ACL 回歸閘門 |
| Stripe 半套封存 | `stripe_webhook.py` 未掛 router | 金流一次做完一家，或明確雙軌，禁止半套 |

### 2.3 Enclave 相對 UniHR 的不可妥協優勢（雲端化時必須保留）

1. **Control Plane + Triple Injection**：解析／連接器／Wiki 可開關，資料權威不外包。  
2. **問答品質架構**：QueryPlan／交付閘門／逐字溯源稽核（shadow→enforce）。  
3. **能力誠信體系**：CV-* 消融閘門、`CAPABILITY_CLAIMS`——雲端行銷文案必須綁此體系。  
4. **地端可選路徑永不放棄**：同一套程式可 Compose 落地——這是差異化，不是過渡期殘留。

---

## 3. 產品形態與販售路線（先定「賣什麼」）

### 3.1 三種官方交付形態（長期並存）

```text
┌──────────────────────────────────────────────────────────────────┐
│                     Enclave Product Family                       │
├──────────────────┬───────────────────────┬───────────────────────┤
│  A. On-Prem      │  B. Managed Private   │  C. Multi-Tenant SaaS │
│  客戶自管地端     │  託管私有雲（每客一套） │  共享控制面多租戶       │
├──────────────────┼───────────────────────┼───────────────────────┤
│ Compose / air-gap│ 你方代管 VM/VPC       │ 單一平台 N 租戶        │
│ 資料不出客戶網    │ 資料邏輯隔離＋專屬實例 │ RLS＋物件前綴＋配額     │
│ 現有主路徑        │ 最快變現的雲端形態     │ 規模化後的主形態        │
└──────────────────┴───────────────────────┴───────────────────────┘
```

| 形態 | 目標客群 | 何時主推 | 隔離強度要求 |
|------|----------|----------|--------------|
| **A 地端** | 金融／醫療／政府／禁雲 | 持續（已有） | 實體隔離（單實例） |
| **B 託管私有雲** | 要雲端便利但要「我的環境」 | **Phase 1 主推** | 實例級隔離（每客 Compose／VPC） |
| **C 多租戶 SaaS** | SMB／中型、願意共享平台 | Phase 2–3 | RLS＋儲存前綴＋sidecar 映射＋配額 |

### 3.2 商業模式（對齊 UniHR 已驗證的 Sales-Led）

| 階段 | 模式 | 說明 |
|------|------|------|
| 0–12 個月 | **Sales-Led + Design Partner** | 後台開戶／顧問導入；不做公開自助試用洪水 |
| 12–24 個月 | Sales-Led + **受控自助註冊**（需 email verify + 人工審核） | 降低 CAC，仍防濫用 |
| 24 個月+ | 可選 Pure PLG（視濫用／成本曲線） | 僅在配額／支付／反濫用齊備後開放 |

### 3.3 方案矩陣（建議對齊並擴充 UniHR）

| 方案 | 定位 | 月查詢（建議起點） | 文件／使用者 | 差異化能力 |
|------|------|-------------------|--------------|------------|
| **Pilot** | Design Partner／POC | 500 | 200 份／10 人 | Base + 問答；無 SSO |
| **Team** | SMB 生產 | 5,000 | 2,000 份／50 人 | + Document Intelligence；shadow 溯源 |
| **Business** | 中型 | 50,000 | 20,000 份／200 人 | + Enterprise Connect；enforce 溯源可選；SSO |
| **Enterprise** | 大客／地端／私有雲 | 合約制 | 合約制 | 全 packs；專屬實例；DPA；SLA；自訂模型路由 |

> 數字為**起始建議**，上線前用 Design Partner 真實用量校正；強制點是「超額 429 + 升級路徑」，不是數字本身。

### 3.4 定價原則（成本非零、但品質優先）

- **品質路徑不打折**：主模型／rerank／OCR 增強臂的成本進入 COGS，用方案邊界吸收，不以降級幻覺換毛利。  
- **稽核層預設走本地／廉價內部模型**（現 `qwen3.6:35b`）；SaaS 可改廉價雲端小模型，但 `SOURCE_VERIFY_MODE` 契約不變。  
- 每個方案必須能算出：**每千次查詢 COGS 上限**（LLM＋embed＋rerank＋OCR＋儲存）。

---

## 4. 雲端化架構目標態（Target Architecture）

### 4.1 邏輯架構（形態 B／C 共用控制面契約）

```text
CDN / WAF (Cloudflare 或同等)
            |
Edge Gateway (TLS, HSTS, CSP, rate-limit)
       /                \
Enclave API (N)      Celery Workers (N)
JWT/SSO/PEP/RLS      queues: default, ingest, bulk
       \                /
        +------+------+------+------+
        |      |      |      |      |
   Postgres  Redis  Object Vector Sidecar Packs
   + RLS     cache  Store  pgvector (RAGFlow /
   (+read           R2/S3/ (+opt.    PipesHub /
    replica)        MinIO   Pinecone/ WeKnora)
                    tenant/ Qdrant)  B: per-customer
                    prefix           C: binding map

Observability: Sentry + Langfuse + Prometheus/Grafana + audit
```

### 4.2 關鍵設計不變量（雲端化後仍必須成立）

| ID | 不變量 | 驗證方式 |
|----|--------|----------|
| INV-DATA | 文件 bytes 與 chunks 的**寫入真相**在 Enclave 控制的儲存／DB，不在 sidecar | 撤權後 1 分鐘內不可檢索（既有 deny-first 測試擴雲） |
| INV-ACL | 列表層與**聊天檢索層** ACL 必須同強度（吸取 UniHR 對考教訓） | 跨部門 chat 洩漏測試進 CI |
| INV-RLS | SaaS 形態下，繞過 ORM 的 raw SQL 仍受 RLS 約束 | RLS 繞過攻擊測試 |
| INV-QA | 雲端化不得降低答題正確率；盲測／主集回歸必過 | `eval_answer_correctness` 進 release gate |
| INV-VERIFY | `SOURCE_VERIFY_MODE` 契約跨環境一致；enforce 上線有獨立決策 | shadow 誤殺率儀表 |
| INV-CLAIMS | 行銷宣稱 ⊆ `CAPABILITY_CLAIMS` 可宣稱集合 | 發布前人工＋腳本對帳 |

### 4.3 部署拓撲選擇（中長期）

| 階段 | 建議 | 理由 |
|------|------|------|
| Phase 1 | **Compose on 託管 VM／VPC**（對齊 UniHR Linode 路徑） | 最快、運維心智與現有 prod compose 一致 |
| Phase 2 | 同 Compose + **讀副本／多 AZ 磁碟／託管 Postgres 選配** | 提升 RPO／RTO，不必上 K8s |
| Phase 3 | 評估 **K8s（EKS／GKE／AKS 或 k3s）** | 僅當形態 C 租戶數／發佈頻率證明 Compose 運維成本過高 |
| 長期 | **多區域**（資料駐留）：`ap-east`／`eu`／`us` 選配 | 合規驅動；模板借鏡 UniHR `MULTI_REGION.md` |

**明確反對**：為了「看起來像雲原生」在 Phase 1 強上 K8s——那是複雜度稅，不是競爭力。

### 4.4 容量模型（基準：100+ 租戶 × 100 使用者 × 500 文件）

> 2026-08-04 容量審查結論：**形態 B 直接達標；形態 C 需補 6 項容量工程（見 WS-CAPACITY）**。
> 本節數字為設計目標，上線前必須以 CG-CAPACITY 負載測試證明，不得以推算代替實測。

**規模推算**

| 維度 | 推算 | 備註 |
|------|------|------|
| 註冊使用者 | 10,000（100 租戶 × 100） | 同時在線估 5–10%＝500–1,000 |
| 文件總量 | 50,000 份 | 每租戶 500；增量為主、開戶為批次 |
| chunks／向量 | ~150 萬（50K × 平均 30 chunks） | pgvector HNSW 百萬級可承載；千萬級才需分區或專用向量庫 |
| 物件儲存 | ~250 GB（50K × 均 5MB） | R2／S3 無壓力 |
| 查詢量 | 日均 ~20 萬次（每人 20 次）；均 ~2–5 QPS、尖峰估 50 QPS | LLM 串流佔連線 30–60s |
| 開戶批次入庫 | 單租戶 500 份須 < 24h | 需 ≥10–20 個解析 worker 並發（見下） |

**各層承載判定（形態 C 單平台）**

| 層 | 判定 | 依據／缺口 |
|----|------|-----------|
| Web API（SSE 聊天） | ✅ 可承載 | async SSE 單進程可持大量長連線；4–8 replicas 足夠；既有 Locust/k6 基準（`tests/load/`）需擴到 1,000 VU 多租戶情境實證 |
| PostgreSQL 連線 | ⚠️ **必須改** | 現 pool 10+20／進程；4 web + 8 worker 即 ~360 連線 > 預設 max_connections=100 → **Phase 2 強制 PgBouncer 或託管 PG** |
| pgvector 檢索 | ✅ 可承載 | 150 萬向量在 HNSW 下為中小規模；慢查詢監控已有（session.py） |
| Redis（cache＋queue） | ✅ 可承載 | 此規模遠低於 Redis 常見負載 |
| Celery 入庫管線 | ⚠️ **必須改** | 無顯式 concurrency 設定（預設=CPU 數）；開戶批次 500 份×RAGFlow 解析 1–5 分/份 → 單機需 8–40 小時 → **worker 必須可水平擴展並設 concurrency** |
| RAGFlow 解析 | ⚠️ 可解（非死路） | **雲端形態（B/C）零 GPU**：數位文件走 RAGFlow CPU 容器池（可水平擴展）；掃描件自動路由 Mistral OCR API（已實測 30.3% 優於 DeepDoc 24.2%、4 美元/千頁，100 萬頁全量約 4,000 美元；觸發邏輯已存在於 cloud_ocr.py）。GPU 僅存在於形態 A（客戶自管地端）——該形態資料不得出客戶環境，本地 GPU 是唯一合法選項，非雲端路線的一部分 |
| LLM API（Luna） | ⚠️ 需管理 | 日均 20 萬次須確認 provider TPM/RPM 額度；需佇列＋退避＋降級（既有 fallback）；成本進 COGS 由方案矩陣吸收 |
| 稽核層（source_verifier） | ⚠️ 需落點決策 | 現跑本地 Ollama qwen3.6:35b（23GB）；零 GPU 雲端 CPU 跑不動 → SaaS 改廉價雲端小模型（見 D7） |
| Embedding（bge-m3） | ⚠️ 需落點決策 | 現跑本地 Ollama；雲端零 GPU 下 CPU embedding 慢 → 建議 Voyage API（已有 key、UniHR 實戰使用中）或 CPU 小實例池（見 D7） |

**形態 B（託管私有雲）判定**：每客戶 100 人／500 份對單實例是**小負載**（現行本機 Pilot 即此量級）；100+ 租戶＝100+ 實例，瓶頸在**開戶自動化（IaC／SOP）與 fleet 監控**，不在單實例容量。這是 Phase 1 主推 B 的核心理由之一。


---

## 5. 工作流（Workstreams）— 完整解決方案

每個工作流含：目標、解法、參照、驗收、風險。

### 5.1 WS-STORAGE — 物件儲存抽象（雲端化地基）

**目標**：上傳／下載／刪除／預簽名 URL 與部署無關。

**解法**

```text
StorageBackend (Protocol)
  ├─ LocalFilesystemBackend      # 現況 / 地端 air-gap
  ├─ S3CompatibleBackend         # R2 / Linode Objects / AWS S3 / MinIO
  └─ (未來) AzureBlobBackend
```

- DB `documents.file_path` → 進化為 `content_uri`（`s3://bucket/tenant/doc/...` 或 `file://...`）。  
- Worker 一律經後端下載到暫存再解析（對齊 UniHR `document_tasks`）。  
- 刪除／撤權：物件刪除 + tombstone + 向量刪除同一事務邊界（outbox）。

**參照**：UniHR `documents.py` R2；Enclave MinIO enterprise overlay。  
**驗收**：上傳→入庫→問答→撤權→物件與向量皆不可達；地端切回 local 回歸綠燈。  
**風險**：大檔 multipart、跨區延遲——Phase 1 先同區。

### 5.2 WS-RLS — 資料庫租戶硬隔離

**目標**：即使應用層 bug，也無法跨租戶讀寫。

**解法（移植 UniHR 模式並加強）**

1. Alembic：核心表 `ENABLE ROW LEVEL SECURITY` + policy `tenant_id = current_setting('app.tenant_id')::uuid`。  
2. 連線中介：`apply_rls_context(tenant_id)`；平台超管 `app.bypass_rls`。  
3. Feature flag：`RLS_ENFORCEMENT_ENABLED`（shadow → enforce，對齊 UniHR rollout）。  
4. **Enclave 加強**：部門 ACL **不**下沉到 RLS（維持 PEP）；RLS 只做租戶邊界，避免政策爆炸。

**驗收**：偽造 JWT tenant、raw SQL、worker 任務、Celery 子程序皆無法讀他租戶；bypass 僅平台角色。  
**風險**：背景任務忘記設 context——所有 task 入口強制 middleware。

### 5.3 WS-SIDECAR-MT — Sidecar 多租戶映射

**目標**：形態 C 下三 sidecar 不變成跨租戶資料湖。

**解法（兩級）**

| 級別 | 適用 | 做法 |
|------|------|------|
| L1 實例隔離 | 形態 B、Enterprise | 每客戶獨立 RAGFlow／WeKnora／PipesHub（或獨立 namespace＋獨立 API key） |
| L2 邏輯映射 | 形態 C | Enclave 維護 `tenant_sidecar_binding`：`tenant_id → {ragflow_dataset, weknora_kb, pipeshub_org, credentials_ref}`；所有呼叫強制經 binding；禁環境變數全局單一 ID |

**驗收**：租戶 A 上傳不可在租戶 B 的 sidecar API 以 B 憑證列出；撤權後 sidecar 投影收斂（既有 outbox SLA）。  
**風險**：這是全計畫**最大工程量**——Phase 1 可用「形態 B 全走 L1」繞開，形態 C 前必須完成 L2。

### 5.4 WS-AUTH — 身分、SSO、MFA、邀請／驗證

**目標**：企業可採購的身分水準。

**解法**

1. **掛載**既有 `sso.py` router；補齊 `TenantSSOConfig` 真模型（修 DD-M09）。  
2. Email 驗證＋密碼重設（SMTP／Resend／SES）。  
3. Admin／owner **強制 TOTP MFA**（對齊 UniHR `ADMIN_2FA.md`；生產啟動阻擋）。  
4. 可選 Cookie session + CSRF（瀏覽器）；API client 維持 Bearer。  
5. 邀請制為預設；自助註冊閘門獨立 flag。

**驗收**：SSO 登入→JWT 含正確 tenant；未驗證不可聊天；MFA 挑戰不可繞。  
**風險**：SSO redirect 白名單、帳號連結攻擊——需專測。

### 5.5 WS-COMMERCE — 方案、配額、金流、帳單

**目標**：可收費、可限流、可升級。

**解法**

1. 固化 `PLAN_MATRIX`（§3.3）與租戶欄位同步（借鏡 `crud_tenant` plan sync）。  
2. FastAPI Depends：`enforce_query_quota`／`enforce_upload_quota`／`enforce_user_quota` → 429 + 機器可讀 `quota_exceeded`。  
3. 每次 chat／OCR／embed 寫 `UsageRecord`（tokens、provider、cost_estimate、trace_id）。  
4. 金流：  
   - TW：**NewebPay**（對齊 UniHR 已上線路徑）  
   - Intl：Stripe（完整 Checkout + webhook + 對帳，或乾脆不做）  
5. Billing API：發票紀錄、升級建議、用量儀表（前端「我的用量」升級）。

**驗收**：超額 429；付款成功自動升等；退訂降級不破壞既有文件（只限新寫入）。  
**風險**：半套金流——發布 checklist 必須含「付款→開通→降級」E2E。

### 5.6 WS-SECURITY — 雲端攻擊面

**目標**：對外暴露後仍敢給客戶機敏文件。

| 控制 | 解法 |
|------|------|
| 上傳掃毒 | ClamAV（fail-closed 於 SaaS／託管）；地端可選 |
| WAF／DDoS | Cloudflare（或同等）在邊緣 |
| 速率限制 | 三層：IP／user／tenant（強化現有 Redis 滑窗） |
| Secrets | 憑證進 KMS／Vault；淘汰純本地 Fernet key 檔（遷移路徑見 UniHR `SECRETS_VAULT_MIGRATION.md`） |
| 安全標頭 | HSTS、CSP、X-Frame DENY（nginx） |
| 滲透 | **HG-PENTEST 關閉前不得宣稱商業 GA**（既有 OPEN_GATES） |
| 租戶隔離紅隊 | 自動化跨租戶／跨部門 chat 洩漏測試（每 release） |

### 5.7 WS-OBSERVABILITY — 可營運

**目標**：出事 5 分鐘內知道「哪個租戶、哪次問答、哪段檢索」。

| 層 | 解法 |
|----|------|
| 錯誤 | **Sentry**（web＋worker） |
| LLM／RAG trace | **Langfuse**（與 `source_verification`、retrieval trace 關聯） |
| 紅燈指標 | 既有 Prometheus／Grafana；補：quota_exceeded、verify_fail_rate、ingest_lag、sidecar_error |
| 稽核 | 既有 audit；補資料刪除／匯出請求軌跡（GDPR／個資法） |
| LLM 健康 | Celery probe（借鏡 UniHR `llm_health_probe`）——避免全站安靜拒答 |

### 5.8 WS-QA-CLOUD — 問答品質不因上雲退化

**目標**：雲端發布 = 品質發布。

**解法**

1. Release gate 強制：主集抽樣 ≥40 題 + 盲測子集 + 對抗集 + ACL 洩漏測。  
2. `SOURCE_VERIFY_MODE`：SaaS 預設 shadow；Business+ 可開 enforce（誤殺率 SLO：<2%）。  
3. 模型路由：租戶可選「品質優先／成本優先」profile，但**不可關閉交付閘門與拒答紀律**。  
4. 持續對照 UniHR 修復計畫中「可反向移植」項——兩邊共用評測題時保持同一 span 正規化。

### 5.9 WS-DATA-RESIDENCY — 資料駐留與退出

**目標**：企業採購必問項一次做對。

| 能力 | 解法 |
|------|------|
| 區域 | 租戶綁定 `region`；物件桶／DB／向量同區 |
| DPA | 範本（參 UniHR `DPA_TEMPLATE.md`）+ 法務簽核閘門 |
| 攜出 | 租戶級 export（文件＋meta＋用量），異步打包至物件儲存 |
| 刪除權 | 硬刪流程＋保留期＋證明報告（`DATA_DELETION_SOP`） |
| 備份／DR | 每日物件＋DB；季度 restore drill；RPO≤24h／RTO≤8h（Phase 1 目標） |

### 5.10 WS-GTM-OPS — 開戶、導入、支援

**目標**：可賣、可交、可養。

1. 平台後台：開租戶／設方案／重設配額／模擬登入（審計）。  
2. Onboarding wizard：公司→邀請→首批上傳→（可選）SSO→驗收題。  
3. Sales-Led runbook：POC 14 天檢查清單（含盲測 10 題客製）。  
4. 狀態頁＋事件通報；客服角色權限（只讀稽核）。

### 5.10a WS-AGENTIC-OPS — AI Agent 車隊維運（2026-08-04 新增）

**背景**：形態 B 的代價是「客戶數＝系統數」。傳統解法（腳本＋值班人力）在 AI agent 時代已過時——維運勞動本身應由 agent 執行，人類只批准例外。Enclave 自身即為 AI agent 產品，車隊維運是最佳 dogfooding 場景。

**模式**：每個客戶實例的監控、更新、故障處理、開通由維運 agent 執行；**人類只在例外時介入**（agent 處理失敗、破壞性操作、客戶溝通）。

| 維運情境 | Agent 行為 | 人類介入點 |
|----------|-----------|-----------|
| 實例故障 | 診斷→重啟／修復→驗證→寫事件報告 | agent 修復失敗時升級 |
| 版本更新 | 批次更新→跑回歸閘門→失敗自動回滾 | 閘門紅燈時批准例外 |
| 新客戶開通 | 全自動拉起實例＋煙霧測試 | 「確認交付」按鈕 |
| 容量／成本 | 預測→擴容→記帳 | 超過預算閾值時批准 |

**護欄（必要）**：agent 對生產實例的破壞性操作需批准閘門（借用 Enclave 既有 review queue 模式）；全部操作寫稽核軌跡；回滾路徑永遠先於執行路徑就緒。

**效果**：B 形態可維持客戶數從「數十」提升至「數百」；維運人力不隨客戶數線性增長。

**不改變的事**：每客戶基礎設施成本仍在（B 定價須涵蓋）；C 形態的隔離驗證（滲透／紅隊）仍需日曆時間與第三方，agent 只能加速工程不能加速信任。

### 5.11 WS-CAPACITY — 容量工程（100+ 租戶基準）

**目標**：形態 C 單平台承載 §4.4 基準負載，且以實測證明。

| 項目 | 解法 |
|------|------|
| DB 連線 | PgBouncer（transaction pooling）或託管 PG；pool 參數隨 replica 數公式化 |
| Worker 擴展 | Celery 顯式 worker_concurrency；ingest queue 獨立；開戶批次可臨時加 worker |
| RAGFlow 池（純 CPU） | 雲端部署不含 GPU：CPU 解析容器依佇列深度水平擴展；掃描件一律路由雲端 OCR API；入庫 SLO：P95 < 30 分 |
| LLM 額度 | provider 額度確認＋429 退避佇列＋降級鏈；每租戶速率公平性（防單一租戶擠兌） |
| 負載測試 | 擴充 `tests/load/`：1,000 VU、多租戶混合情境、開戶批次風暴；進 release gate |
| 容量儀表 | Grafana：每租戶 QPS／入庫延遲／LLM 錯誤率／DB 連線使用率 |
| 內部模型落點 | 稽核／embedding／scan 三角色在雲端的 provider 切換（`deployment_mode.py` 已抽象，僅需設定與回歸驗證） |

**驗收（CG-CAPACITY）**：1,000 VU 多租戶 30 分鐘：chat P95 < 5s、錯誤率 < 2%；單租戶 500 份批次入庫 < 24h；DB 連線使用率 < 70%。


---

## 6. 分階段路線圖（18–24 個月）

### Phase 0 — 決策與邊界修訂（2–4 週）

| 交付 | 完成判準 |
|------|----------|
| 採納本計畫；修訂 ADR-003（允許 SaaS 工作流，仍保留地端主路徑） | ADR-003v2 Accepted |
| 選定首發雲形態：**B 託管私有雲** 為主、C 為平行研發 | 產品／業務書面確認 |
| 選定雲供應商組合（建議起點：邊緣 CF + 物件 R2 或 Linode Objects + 計算 Linode／同等） | 架構決策一頁紙 |
| 法律啟動：DPA 草稿、模型商用授權盤點（HG-LEGAL） | 法務排程 |

### Phase 1 — 雲端可賣的「託管私有雲」（約 2–3 個月）★ 最快變現

> 形態 B：每客戶獨立實例。**刻意不做共享多租戶**，以換取速度與隔離強度。

| 工作流 | 必做項 |
|--------|--------|
| WS-STORAGE | S3 相容後端 + 遷移腳本（local→object） |
| WS-AUTH | SSO 掛載、email verify、owner MFA |
| WS-COMMERCE | 配額強制 + 用量儀表；**金流 Phase 1 直接接 NewebPay**（D3 定案，不做手動過渡） |
| WS-SECURITY | ClamAV、WAF、三層限流、secrets 基本盤 |
| WS-OBSERVABILITY | Sentry + Langfuse + 既有 Prom |
| WS-QA-CLOUD | 發布閘門腳本 |
| WS-GTM-OPS | 開戶 SOP、POC runbook |
| WS-DATA-RESIDENCY | 備份／還原演練 1 次；DPA 可簽 |

**出口（Phase 1 Done）**

- [ ] 新客戶實例由維運 agent 全自動拉起＋煙霧測試，人類僅按「確認交付」（WS-AGENTIC-OPS）  
- [ ] 客戶可 SSO 登入、上傳、問答；盲測回歸不劣於地端  
- [ ] 超額被擋；用量可查  
- [ ] 外部滲透針對**託管環境**至少完成一輪（或明確風險接受文件）  
- [ ] 首批 Design Partner ≥1 付費或等價合約

### Phase 2 — 多租戶 SaaS 控制面（約 3–5 個月）

| 工作流 | 必做項 |
|--------|--------|
| WS-RLS | RLS shadow→enforce |
| WS-SIDECAR-MT | L2 binding 表 + 全路徑強制 |
| WS-COMMERCE | NewebPay 已於 P1 上線；P2 補 Stripe（國際）或維持單軌 |
| WS-AUTH | 受控自助註冊 flag |
| WS-SECURITY | 跨租戶紅隊自動化進 CI |
| WS-QA-CLOUD | 每租戶 canary 題庫 |

**出口（Phase 2 Done）**

- [ ] 單平台租戶數分級驗證：N≥10（功能）→ N≥50（容量）→ N≥100（CG-CAPACITY 負載實測）各穩定運行 30 天  
- [ ] RLS 繞過測試 0 洩漏  
- [ ] Sidecar 映射無全局單一 dataset  
- [ ] 付款→開通→降級 E2E 綠燈  
- [ ] 對考級 ACL chat 測試永續綠燈

### Phase 3 — 規模化與合規深化（約 6–12 個月）

| 主題 | 內容 |
|------|------|
| 多區域資料駐留 | 區域選項 + 禁止跨區副本（除非客戶同意） |
| HA／效能 | 託管 Postgres、讀副本、物件跨 AZ；評估 K8s |
| 進階企業 | SCIM、自訂網域＋自動化 SSL、專屬 VPC peering、自帶金鑰（CMK） |
| 品質產品化 | enforce 溯源預設開給 Business+；租戶級品質儀表板 |
| 生態 | 公開 API／webhook；可選 Marketplace 連接器（SP／Drive OAuth 重啟） |

**出口（Phase 3 Done）**：可宣稱「多區域企業級 SaaS」且聲稱 ⊆ Claims；DR 演練達標；滲透複測關閉。

---

## 7. 與 ADR-003 的關係（必要修訂草案）

現行 ADR-003「明確不做」將改寫為：

| 原決策 | 修訂後 |
|--------|--------|
| 不做計費／試用／自助註冊 | **Phase 0–1 仍可不做自助**；Phase 2 起允許受控註冊與金流 |
| 不引入共享向量庫 | 形態 B 維持；形態 C 允許**邏輯共享基礎設施**，但寫入真相與 ACL 不放寬 |
| 不做多區域 | Phase 3 允許；Phase 1–2 單區域 |
| 不引入 K8s | Phase 1–2 維持；Phase 3 評估 |

地端單客戶路徑**永不刪除**——雲端化是產品族擴張，不是取代。

---

## 8. 風險登記（中長期）

| ID | 風險 | 等級 | 緩解 |
|----|------|------|------|
| R1 | Sidecar 共享造成跨租戶洩漏 | 極高 | Phase 1 只用實例隔離；Phase 2 強制 binding＋紅隊 |
| R2 | 上雲後 COGS 失控（LLM＋OCR＋rerank） | 高 | 方案矩陣＋每千次查詢預算＋租戶路由 profile |
| R3 | 半套金流／半套 SSO 重蹈 UniHR／舊 SaaS 殘留 | 高 | 發布 checklist 禁止「程式存在但未掛」進 GA |
| R4 | 為趕 SaaS 犧牲答題品質 | 極高 | INV-QA 發布閘門；品質回歸失敗 = 禁止發版 |
| R5 | 法律／滲透未關就對外販售 | 極高 | OPEN_GATES 人工閘門綁定商業合約 |
| R6 | 地端與雲端程式分叉 | 中 | 單一 repo；`STORAGE_BACKEND`／`DEPLOYMENT_PROFILE` 開關 |
| R7 | 過度 K8s 化拖慢變現 | 中 | Phase 1 鎖定 Compose |
| R8 | 自助註冊被濫用洗額度 | 中 | Sales-Led 優先；註冊審核＋嚴格 Pilot 配額 |
| R9 | 形態 C 容量不足（DB 連線／RAGFlow 序列化／LLM 額度） | 高 | WS-CAPACITY 六項工程；CG-CAPACITY 未過不得對 C 形態招商 |
| R10 | 維運 agent 對生產實例誤操作 | 高 | 破壞性操作批准閘門＋完整稽核＋回滾優先（WS-AGENTIC-OPS 護欄） |

---

## 9. 組織與決策點（需要人拍板的事項）

| # | 決策 | 定案（2026-08-04） | 理由 |
|---|------|------|------|
| D1 | 首發雲形態 | ✅ **B 主推銷售；C 隔離工程由 AI agent 立即動工** | 最快變現＋隔離風險最高的部分提前啃 |
| D2 | 雲供應商 | ✅ **Cloudflare＋R2＋Linode** | 延續 UniHR 生產營運經驗，坑已踩過 |
| D3 | 金流 | ✅ **Phase 1 直接接 NewebPay**（不做手動過渡） | 與 D1 同思維：一步到位，避免半套 |
| D4 | 向量 | ✅ **pgvector**（自家 PG，寫入真相） | 目標規模 150 萬向量／50 QPS 在 pgvector 甜區內，效能不輸託管；託管向量是千萬級規模的選項而非升級；避免雙系統同步複雜度（UniHR 為此需專文審計） |
| D5 | 自助註冊 | ✅ **12 個月內不開**，Sales-Led 開戶 | 防濫用洗額度 |
| D6 | enforce 溯源預設 | ✅ **方案分級**（Team shadow／Business+ enforce） | enforce＝「寧可保守不可編造」，不提升答題聰明度；誤殺率 1-2%，故不對全方案強制 |
| D7 | 雲端內部模型 | ✅ **Voyage embeddings**；稽核模型**品質優先**（建議 Terra 等級，不挑最便宜） | 稽核呼叫量 ≈ 主模型（每題一次且輸入更長），非小用量；稽核員太弱會誤殺／漏抓 |

---

## 10. 成功指標（18 個月）

| 指標 | 目標 |
|------|------|
| 付費雲端客戶（B 或 C） | ≥ 3（含至少 1 個 Enterprise 託管） |
| 地端客戶不流失 | 既有地端路徑持續可安裝升級 |
| 答題品質 | 主集／盲測發布閘門持續 ≥ 既有基線 |
| 隔離事故 | 跨租戶洩漏 **0**（生產） |
| 營運 | P1 事故 MTTD＜15m；季度 DR drill 通過 |
| 宣稱誠信 | 對外文案 100% 可映射 `CAPABILITY_CLAIMS` |

---

## 11. 建議的文件／程式落地清單（開工用）

### 11.1 文件

- [x] `docs/adr/ADR-003` → v2（本計畫 §7）  
- [x] `docs/adr/ADR-011-storage-backend.md`（新增）  
- [x] `docs/adr/ADR-012-tenant-rls.md`（新增）  
- [x] `docs/adr/ADR-013-sidecar-tenant-binding.md`（新增）  
- [x] `docs/runbooks/MANAGED_PRIVATE_CLOUD.md`（Phase 1 SOP）  
- [x] `docs/runbooks/SAAS_TENANT_ONBOARDING.md`  
- [x] `docs/legal/DPA_TEMPLATE.md`（草稿；HG-LEGAL 簽核仍開放）  
- [x] 更新 `README.md` 產品族三種形態說明（採納後）  
- [x] 更新 `OPEN_GATES.md`：新增雲端閘門 ID（見下）

### 11.2 新增雲端閘門 ID（建議寫入 OPEN_GATES）

| ID | 項目 | 階段 |
|----|------|------|
| CG-STORAGE | StorageBackend 雙路徑（local＋S3）驗收 | P1 |
| CG-AUTH-SSO | SSO＋email verify＋owner MFA | P1 |
| CG-QUOTA | 三軸配額 429＋用量儀表 | P1 |
| CG-OBS | Sentry＋Langfuse 串問答 trace | P1 |
| CG-CLAMAV | SaaS／託管上傳掃毒 fail-closed | P1 |
| CG-RLS | RLS enforce＋繞過測試 | P2 |
| CG-SIDECAR-MT | sidecar binding 無全局單 ID | P2 |
| CG-CAPACITY | 100 租戶×100 人×500 文件負載實測（§4.4／§5.11） | P2 |
| CG-PAY | 金流閉環 E2E（NewebPay） | P1（D3 定案提前） |
| CG-REGION | 多區域資料駐留 | P3 |
| HG-PENTEST-CLOUD | 針對託管／SaaS 環境之滲透 | P1／P2 |
| HG-LEGAL | （既有）模型／依賴商用授權 | 持續 |
| HG-DR-SIGN | （既有）DR／安裝簽核 | 持續 |

### 11.3 程式模組（建議路徑）

```text
app/services/storage/
  base.py              # Protocol
  local.py
  s3_compatible.py
app/services/rls.py                # apply_rls_context
app/models/tenant_sidecar_binding.py
app/api/v1/endpoints/subscription.py   # 若尚未獨立
app/api/v1/endpoints/billing.py
app/middleware/quota.py
app/observability/sentry.py
app/observability/langfuse_client.py
```

---

## 12. 明確不做（本計畫邊界）

避免範圍爆炸，下列**不在**本計畫承諾內：

1. 重寫問答引擎或放棄 Triple Injection。  
2. Phase 1 強上 Kubernetes。  
3. 公開無限量免費試用（無配額）。  
4. 把資料權威下放給 RAGFlow／Pinecone／任一 SaaS 向量商。  
5. 為趕進度關閉 `CAPABILITY_CLAIMS` 誠信閘門或跳過滲透。  
6. 與 UniHR 合併成單一產品碼——可共享模式與評測，**保持產品獨立**。

---

## 13. 下一步（採納後立即執行）

1. **拍板 D1–D6**（§9）。  
2. 修訂 ADR-003 v2。  
3. 開 Phase 1 epic：`CG-STORAGE` → `CG-AUTH-SSO` → `CG-QUOTA` → `CG-OBS` → 託管 POC 實例。  
4. 法務啟動 HG-LEGAL／DPA；排程 HG-PENTEST-CLOUD。  
5. README／OPEN_GATES 掛上本文件連結與閘門 ID。

---

## 14. 結語

Enclave 雲端化**完全可行**——不是因為「把 Docker 丟上 VM」就算雲，而是因為：

- 多租戶資料模型與 PEP **已經預留**（ADR-003 當初的遠見）；  
- 問答品質有**可回歸的架構與數字**；  
- UniHR 提供了**可抄作業的商業殼層實戰地圖**（RLS、R2、配額、金流、觀測、Sales-Led）。

真正的工作是拆成：**先賣得動的託管私有雲（Phase 1）→ 再做規模化多租戶（Phase 2）→ 最後合規與多區域（Phase 3）**，全程用閘門與誠信宣稱約束，避免「看起來是 SaaS、實際上是半套」。

**本文件是路線圖，不是已完成聲明。** 採納前請完成 §9 決策；採納後以 §11 閘門為唯一進度語言。

---

## 15. 附錄：雲端資源／服務總表（2026-08-04）

> 本表彙整計畫採用的所有外部雲端資源。形態欄：A＝地端自管、B＝託管私有雲、C＝多租戶 SaaS。
> 原則：**雲端形態零 GPU**；每項皆標註地端替代（形態 A 不使用任何外部雲端資源）。

### 15.1 邊緣與網路

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **Cloudflare**（或同等） | CDN、WAF、DDoS 防護、TLS 終止 | B、C | P1 | 免費～Pro 級即夠初期 |

### 15.2 計算與部署

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **Linode VM／VPC**（或 AWS／GCP 同等） | Compose 部署 API／worker／DB | B、C | P1–P2 | 延續 UniHR 營運經驗（D2） |
| **託管 PostgreSQL**（選配） | 取代自管 PG | C | P2–P3 | 含自動備份／failover |
| **PgBouncer** | DB 連線池（自架、非雲服務） | C | P2 | CG-CAPACITY 前置 |
| **K8s（EKS／GKE／AKS 或 k3s）** | 僅規模證明需要時評估 | C | P3 | 明確不在 P1–P2 |

### 15.3 儲存

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **Cloudflare R2**（首選）或 Linode Object Storage／AWS S3 | 文件物件儲存（S3 API） | B、C | P1 | key 前綴隔離租戶；地端用 MinIO／本地 |
| **pgvector**（自管 PG 內） | 向量索引＝寫入真相 | A、B、C | 既有 | 預設不外包 |
| **Pinecone／Qdrant Cloud**（選配） | 託管向量（大規模時） | C | P2+ | D4；PG 永遠是真相來源 |

### 15.4 AI 模型服務

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **OpenAI gpt-5.6-luna** | 主問答 LLM | A、B、C | 既有 | 盲測對決定案；Sol 退場 |
| **OpenAI gpt-5.6-terra** | 備用／升級（enforce 重生成、高難意圖） | A、B、C | 既有 | 僅升級路徑呼叫 |
| **Voyage AI rerank-2.5** | 檢索重排序 | A、B、C | 既有 | API key 已驗證 |
| **Voyage AI embeddings** | 雲端形態 embedding | B、C | P1（D7） | 地端維持本地 bge-m3 |
| **Mistral OCR API** | 掃描件 OCR（雲端形態預設） | B、C | P1 | 實測 30.3% 優於地端 DeepDoc；4 美元/千頁 |
| **Gemini／OpenAI 雲端 OCR** | OCR 替代供應商 | B、C | 選配 | `cloud_ocr.py` 已抽象 |
| **廉價雲端小模型**（稽核用） | 逐字溯源稽核（SaaS） | B、C | P1（D7） | 地端維持本地 qwen3.6:35b |

### 15.5 金流與商業

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **NewebPay 藍新金流** | 台灣市場收款 | B、C | P2 | 對齊 UniHR 已上線路徑 |
| **Stripe**（完整實作或不做） | 國際市場收款 | C | P2+ | 禁止半套（UniHR 教訓） |

### 15.6 身分與通訊

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **Google／Microsoft OAuth** | 企業 SSO | B、C | P1 | 掛載既有 skeleton |
| **SMTP／Resend／AWS SES** | 交易郵件（驗證／邀請／重設） | B、C | P1 | 擇一 |

### 15.7 觀測與安全

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **Sentry** | 錯誤追蹤（web＋worker） | B、C | P1 | |
| **Langfuse**（雲端或自架） | LLM／RAG trace，串 source_verification | B、C | P1 | 自架則無外部依賴 |
| **Prometheus＋Grafana**（自架） | 指標與儀表 | A、B、C | 既有 | 非外部雲服務 |
| **ClamAV**（自架容器） | 上傳掃毒 fail-closed | B、C | P1 | 非外部雲服務 |
| **KMS／Vault** | Secrets 管理 | B、C | P1–P2 | 淘汰純本地 Fernet key 檔 |

### 15.8 自架 sidecar（非外部雲服務，列此供完整對照）

| 元件 | 雲端形態部署方式 |
|------|------------------|
| RAGFlow | **純 CPU 容器池**（掃描件路由 Mistral OCR API） |
| PipesHub | B：每客專屬；C：binding 映射 |
| WeKnora | 同上 |
| Redis | 自管或託管（cache＋Celery queue） |

### 15.9 成本量級速查（形態 C、100 租戶基準）

| 項目 | 量級估算 | 依據 |
|------|----------|------|
| Mistral OCR（開戶全量 100 萬頁） | 約 4,000 美元一次性 | 4 美元/千頁 |
| LLM（Luna，日均 20 萬次查詢） | 依 Luna 單價計；較 Sol 省一個量級 | 消融對決後定案 |
| R2 儲存（250 GB） | 每月數美元級 | R2 無 egress 費 |
| VM／託管 PG | 每月數百美元級（P1–P2 Compose 規模） | Linode 級定價 |

> 原則：品質路徑成本進 COGS 由方案矩陣吸收（§3.4）；每千次查詢 COGS 上限為方案設計必要輸入。

