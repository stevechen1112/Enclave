# Enclave 產品整合審查報告

> **審查角色**: 資深產品經理
> **審查範圍**: Phase 1-8 (aihr 原始系統) + Phase 9-13 (Enclave 延伸)
> **審查日期**: 2026-02-24
> **結論**: **未達到完美整合，存在 14 項必修缺陷與 19 項應修問題**

---

## 一、整體架構評估

### 技術棧全貌

| 層 | 技術 |
|---|---|
| 前端 Web | React 19 + TypeScript + Vite |
| 前端 Mobile | React Native (Expo) |
| 後端 API | FastAPI + SQLAlchemy + Pydantic v2 |
| 背景任務 | Celery + Redis |
| 資料庫 | PostgreSQL 15 + pgvector |
| LLM | OpenAI GPT-4o-mini / Ollama (可切換) |
| 向量模型 | Voyage AI voyage-4-lite (1024 dim) |

### Phase 對應表

| Phase | 範圍 | 狀態 |
|---|---|---|
| 1-2 | 多租戶 + 帳號管理 | ✅ 已完成 |
| 3-4 | 文件管理 + RAG 檢索 | ✅ 已完成 |
| 5-6 | AI 問答 + 串流 + 回饋 | ✅ 已完成 |
| 7-8 | 稽核安全 + 生產加固 | ✅ 已完成 |
| 9 | SaaS → 地端轉型 | ⚠️ 半完成 |
| 10 | 主動索引 Agent | ⚠️ 骨架完成，有整合缺陷 |
| 11 | 內容生成 | ⚠️ 骨架完成，有斷裂參照 |
| 12 | 行動 App | ⚠️ 骨架完成，SSE 協議不匹配 |
| 13 | 知識庫維護 | ⚠️ 功能完成，缺 Migration |

---

## 二、必修缺陷 (CRITICAL) — 14 項

> 以下問題**會導致執行時錯誤、資料不一致、或功能完全無法使用**。

### C-01 | Phase 13 六張資料表缺少 Migration

**位置**: [app/models/kb_maintenance.py](app/models/kb_maintenance.py)
**問題**: `documentversions`、`categories`、`categoryrevisions`、`kbbackups`、`knowledgegaps`、`integrityreports` 六張表**沒有任何 Alembic migration**。執行 `alembic upgrade head` 不會建立這些表，Phase 13 所有 API 呼叫都會拋出 `ProgrammingError: relation "xxx" does not exist`。
**影響**: Phase 13 全部癱瘓。
**修復**: 建立新的 migration 檔案，一次性 `CREATE TABLE` 這六張表。

---

### C-02 | 雙 Migration 目錄衝突

**位置**: [alembic.ini](alembic.ini) → `script_location = app/db/migrations`，但 [alembic/versions/](alembic/versions/) 另有 6 個 migration 檔。
**問題**: `alembic.ini` 只認 `app/db/migrations/versions/`，所以 `alembic/versions/` 底下的 migration 永遠不會被執行。受影響的表：

| Migration | 建立的表/變更 |
|---|---|
| `t7_5_feedback` | `chat_feedbacks` |
| `p10_watch_folders_and_review_items` | `watch_folders`, `review_items` |
| `t4_3_branding` | 品牌欄位 (還有表名 bug) |
| `t4_6_custom_domain` | `customdomain` |
| `t4_15_db_indexes` | 效能索引 |
| `t4_19_multi_region` | 多區域欄位 |

**影響**: `chat_feedbacks`、`watch_folders`、`review_items` 三張表在生產環境不存在。Phase 10 Agent 功能癱瘓、回饋功能癱瘓。
**修復**: 將 `alembic/versions/` 內容合併到 `app/db/migrations/versions/`，修正 revision chain。

---

### C-03 | Phase 10 Model 用 `org_id` 而非 `tenant_id`，且無 ForeignKey

**位置**: [app/models/watch_folder.py](app/models/watch_folder.py)、[app/models/review_item.py](app/models/review_item.py)
**問題**:
- 命名不一致：Phase 1-8 + 13 全部使用 `tenant_id`，Phase 10 獨用 `org_id`。
- `org_id` 沒有 `ForeignKey("tenants.id")` 約束 — 資料庫層面完全不做參照完整性檢查。
- 零 `relationship()` 宣告 — 完全脫離 ORM 物件圖譜。

**影響**: 無法 JOIN 到 `tenants` 表；任何通用的 tenant 過濾 middleware 都對不上欄位名；孤兒資料可能堆積。
**修復**: 改名 `org_id` → `tenant_id`，加上 `ForeignKey("tenants.id")`，加上 `relationship()`。

---

### C-04 | Category 自參照 relationship 名稱反轉

**位置**: [app/models/kb_maintenance.py](app/models/kb_maintenance.py) line 78
```python
children = relationship("Category", backref="parent", remote_side=[id])
```
**問題**: 使用 `remote_side=[id]` 時，正向 relationship 載入的是 **parent** (跟隨 `parent_id` → `id`)，但命名卻是 `children`；`backref="parent"` 建立的反向 relationship 載入的是 **children**，但命名卻是 `parent`。
對照正確寫法 (Department model)：
```python
parent = relationship("Department", remote_side=[id], back_populates="children")
children = relationship("Department", back_populates="parent")
```
**影響**: `category.children` 回傳父節點、`category.parent` 回傳子節點 — runtime 邏輯完全顛倒。所有使用分類樹的功能都會錯。
**修復**: 改為 `parent = relationship("Category", remote_side=[id], back_populates="children"); children = relationship("Category", back_populates="parent")`。

---

### C-05 | companyApi 前端全部 404 — 8 個呼叫 5 個無後端

**位置**: [frontend/src/api.ts](frontend/src/api.ts) lines 144-154
**問題**: 前端 `companyApi` 呼叫 `/company/*`，但後端只有 `/admin/*` 路由。

| 前端路徑 | 後端對應 | 狀態 |
|---|---|---|
| `/company/dashboard` | `/admin/dashboard` | 路徑錯 |
| `/company/profile` | 不存在 | **缺實作** |
| `/company/users` | `/admin/users` | 路徑錯 |
| `/company/users/invite` | 不存在 | **缺實作** |
| `/company/users/{id}` (PUT) | 不存在 | **缺實作** |
| `/company/users/{id}` (DELETE) | 不存在 | **缺實作** |
| `/company/usage/summary` | 不存在 | **缺實作** |
| `/company/usage/by-user` | 不存在 | **缺實作** |

**影響**: [CompanyPage.tsx](frontend/src/pages/CompanyPage.tsx) 整頁癱瘓，組織管理功能不可用。
**修復**: 在後端建立 `/company` 路由或在前端改用 `/admin` + 補齊 5 個缺失 endpoint。

---

### C-06 | Mobile SSE 事件欄位名全錯

**位置**: [mobile/src/types.ts](mobile/src/types.ts)
**問題**:

| 後端送出 | Mobile 期望 |
|---|---|
| `{type:'token', content:'...'}` | `{type:'token', token:'...'}` |
| `{type:'status', content:'...'}` | `{type:'status', status:'...'}` |
| `{type:'suggestions', items:[...]}` | `{type:'suggestions', suggestions:[...]}` |
| `{type:'done', message_id, conversation_id}` | 分成獨立的 `conversation_id` 和 `message_id` 事件 |

**影響**: Mobile 聊天串流功能完全無效 — 所有 token、狀態、建議都會被靜默丟棄。
**修復**: 對齊 Mobile `SSEEvent` 型別與後端格式。

---

### C-07 | Mobile ChatSource 介面不匹配

**位置**: [mobile/src/types.ts](mobile/src/types.ts)
**問題**:

| 後端欄位 | Mobile 期望的欄位 |
|---|---|
| `title` | `filename` |
| `snippet` | `chunk_text` |
| `type` | (缺) |

**影響**: Mobile 來源引用面板顯示空白。
**修復**: 更新 Mobile `ChatSource` 介面。

---

### C-08 | generate.py 參照不存在的 Document 欄位

**位置**: [app/api/v1/endpoints/generate.py](app/api/v1/endpoints/generate.py) lines 103-104
```python
content_preview = (doc.content or "")[:2000]  # Document 沒有 content 欄位
parts.append(f"【{doc.title or doc.filename}】...")  # Document 沒有 title 欄位
```
**問題**: `Document` model 沒有 `content` 和 `title` 欄位。SQLAlchemy 不會拋錯但回傳 `None`。
**影響**: Phase 11 跨文件上下文功能 (P11-3) 永遠傳空字串給 LLM，等於無效。
**修復**: 使用 `doc.filename` 代替 `doc.title`；把文件實際內容從 `DocumentChunk.text` 拼接取得。

---

### C-09 | AuditLog Schema 欄位名與 Model 不對齊

**位置**: [app/schemas/audit.py](app/schemas/audit.py) vs [app/models/audit.py](app/models/audit.py)

| Schema 欄位 | Model 欄位 |
|---|---|
| `resource_type` | `target_type` |
| `resource_id` | `target_id` |
| `details` | `detail_json` |

**問題**: Pydantic 的 `from_attributes = True` 靠欄位名自動對映，名稱不同就會回傳 `null`。雖然 CRUD 層手動轉換彌補了部分場景，但透過 ORM 直接序列化時仍會壞。
**影響**: 稽核日誌 API 回傳不完整的資料。
**修復**: Schema 改用 `Field(alias=...)` 或統一命名。

---

### C-10 | DocumentChunk Schema `content` vs Model `text` 名稱衝突

**位置**: [app/schemas/document.py](app/schemas/document.py) line 63 — `content: Optional[str]`，但 [app/models/document.py](app/models/document.py) line 40 — `text = Column(Text)`
**問題**: `from_attributes = True` 自動序列化時，`content` 找不到 model 上的 `content` 屬性，會傳 `null`。
**影響**: 所有回傳 DocumentChunk 的 API 的 `content` 欄位永遠是空值。
**修復**: Schema 改名 `content` → `text`，或加 `Field(alias="text")`。

---

### C-11 | Chat 路由衝突 — conversations/search 不可達

**位置**: [app/api/v1/endpoints/chat.py](app/api/v1/endpoints/chat.py)
**問題**: `GET /conversations/{conversation_id}` 定義在 `GET /conversations/search` 之前。FastAPI 按順序匹配，`/conversations/search` 會被當成 `conversation_id="search"` 而觸發 UUID 驗證失敗 (422)。
**影響**: 對話搜尋功能完全無法使用。
**修復**: 將 `/conversations/search` 路由移到 `/{conversation_id}` 之前。

---

### C-12 | KnowledgeGap 的 conversation_id / message_id 缺 ForeignKey

**位置**: [app/models/kb_maintenance.py](app/models/kb_maintenance.py)
**問題**: `conversation_id` 和 `message_id` 是裸 UUID 欄位，沒有 `ForeignKey` 約束。
**影響**: 資料庫不保證參照完整性，可能產生指向不存在 conversation/message 的孤兒記錄。
**修復**: 加上 `ForeignKey("conversations.id")` 和 `ForeignKey("messages.id")`。

---

### C-13 | generate.py `/templates` 無認證

**位置**: [app/api/v1/endpoints/generate.py](app/api/v1/endpoints/generate.py)
**問題**: `GET /generate/templates` 端點無需任何認證即可存取，洩漏系統可用的文件生成範本資訊。
**影響**: 未授權使用者可取得系統架構資訊。
**修復**: 加上 `Depends(get_current_active_user)`。

---

### C-14 | Agent 審核操作缺 Tenant 隔離

**位置**: [app/api/v1/endpoints/agent.py](app/api/v1/endpoints/agent.py) — `approve_item`, `reject_item`, `modify_item`
**問題**: 這些端點僅檢查使用者角色 (`_admin_only`)，不驗證 `ReviewItem.org_id` 是否等於 `current_user.tenant_id`。
**影響**: 在多租戶殘留的環境下，A 租戶的 admin 可以透過猜測 ID 操作 B 租戶的審核項目。
**修復**: 在操作前加 `item.org_id == current_user.tenant_id` 檢查。

---

## 三、應修問題 (HIGH / MEDIUM) — 19 項

### H-01 | Phase 10 DateTime 不帶 timezone

WatchFolder、ReviewItem 使用 `DateTime` (無 timezone) + `default=datetime.utcnow`，其餘所有 model 使用 `DateTime(timezone=True)` + `server_default=func.now()`。資料庫時區查詢結果會不一致。

### H-02 | auth.py Token 到期時間寫死

[auth.py](app/api/v1/endpoints/auth.py) 硬編碼 `timedelta(minutes=60*24*8)` 而非使用 `settings.ACCESS_TOKEN_EXPIRE_MINUTES`。

### H-03 | audit.py 成本費率寫死

`COST_PER_INPUT_TOKEN` 等常數寫死在程式碼中，應移至 Settings。

### H-04 | generate.py 不記錄 Usage

`/generate/stream` 未呼叫 `log_usage()`，生成消耗的 token 不會出現在用量儀表板。

### H-05 | kb_maintenance.py 分類 CRUD 缺角色檢查

`create_category`、`update_category`、`delete_category`、`rollback_category` 任何已認證使用者都可操作，缺少 admin/owner 角色限制。

### H-06 | kb_maintenance.py KB 健康度缺角色檢查

`GET /kb/health` 任何已認證使用者都可查看完整健康度資訊。

### H-07 | mobile.py 路由無 prefix — 路徑空間衝突

Mobile router 未設 prefix，`/auth/refresh-token` 與 `auth.py` 的 `/auth/*` 路徑空間重疊，`/users/me/push-token` 與 `users.py` 的 `/users/me` 重疊。

### H-08 | ProgressDashboardPage 死連結

[ProgressDashboardPage.tsx](frontend/src/pages/ProgressDashboardPage.tsx) 導航到 `/agent/queue`，但路由只定義了 `/agent/review`。

### H-09 | analytics.py SaaS 殘留

`monthly-by-tenant`、`anomalies`、`budget-alerts` 三個端點是跨租戶分析，在地端單組織架構下無意義且可能洩漏資料。

### H-10 | SSO Schema 有 migration 但無 Model

`tenant_sso_configs` 表有 migration 和 schema，但 `app/models/` 裡沒有對應的 SQLAlchemy model 類別。

### H-11 | DocumentVersionOut Schema 欄位不完整

缺少 `tenant_id`、`file_path`、`quality_report`、`content_snapshot` — model 上有但 API 不回傳。

### H-12 | chat.py feedback/stats 缺角色檢查

任何已認證使用者都可查看租戶整體的回饋統計。

### H-13 | Phase 10/13 九個 Model 缺 CRUD 層

WatchFolder、ReviewItem、DocumentVersion、Category、CategoryRevision、KBBackup、KnowledgeGap、IntegrityReport、FeatureFlag — 全部直接在 endpoint 或 service 裡做 inline ORM，不通過 CRUD 層。專案 Phase 1-8 的 Pattern 是統一走 CRUD，Phase 9+ 偏離了這個慣例。

### H-14 | crud_user.py 功能不足

僅有 `get_by_email`、`create`、`authenticate`，缺少 `get(id)`、`update`、`delete`、`list_by_tenant`。endpoint 層需要自行拼 query。

### H-15 | GeneratePage 期望 wrapper 物件但後端回裸陣列

前端呼叫 `/documents` 期望 `{documents: [...]}` wrapper，後端回傳裸 `List[Document]`。有 fallback 可用但 primary path 永遠失敗。

### H-16 | ChatFeedback Model 零 relationship

有 3 個 FK (`tenant_id`, `message_id`, `user_id`) 但沒有任何 `relationship()` 宣告。

### H-17 | mobile.py Push Token 存在 AuditLog

Push token 以 AuditLog 方式儲存而非獨立表 — 無法有效查詢用於推播送達。

### H-18 | mobile.py 繞過 crud_audit 直接建 AuditLog ORM

Mobile endpoint 直接 `AuditLog(...)` 建立記錄，不走 `crud_audit.create_audit_log()`，可能遺漏 CRUD 層的驗證/轉換邏輯。

### H-19 | 初始 Migration 與 Model 嚴重漂移

初始 migration 的 `tenants` 表有 `tax_id`、`contact_name` 等已刪除欄位；缺少 `max_users`、`max_documents` 等 quota 欄位。`documents` 表缺 `file_size`、`chunk_count`、`quality_report`。`documentchunks` 缺 `vector_id`。

---

## 四、Phase 整合矩陣

下表檢視每一對 Phase 之間的整合狀態。

| 整合路徑 | 狀態 | 斷點 |
|---|---|---|
| P1-2 (帳號) ↔ P3-4 (文件) | ✅ 良好 | — |
| P1-2 (帳號) ↔ P5-6 (問答) | ✅ 良好 | — |
| P5-6 (問答) ↔ P7-8 (稽核) | ⚠️ 部分 | AuditLog schema/model 欄位不對 (C-09) |
| P1-8 ↔ P9 (地端轉型) | ⚠️ 半完成 | analytics.py 仍是 SaaS 架構 (H-09)；companyApi 404 (C-05) |
| P1-8 ↔ P10 (Agent) | ❌ 斷裂 | org_id vs tenant_id (C-03)；migration 在錯誤目錄 (C-02)；審核缺隔離 (C-14) |
| P1-8 ↔ P11 (生成) | ⚠️ 部分 | Document 欄位不存在 (C-08)；templates 無認證 (C-13)；無 usage log (H-04) |
| P1-8 ↔ P12 (Mobile) | ❌ 斷裂 | SSE 協議不匹配 (C-06, C-07)；路由無 prefix (H-07) |
| P1-8 ↔ P13 (維護) | ⚠️ 部分 | 缺 migration (C-01)；Category 反轉 (C-04)；KnowledgeGap 缺 FK (C-12) |
| P10 ↔ P13 | ⚠️ 弱耦合 | 分類體系未互通：P10 用 `suggested_category` 字串，P13 有 `Category` model 但兩者無 FK 連結 |
| P11 ↔ P13 | ⚠️ 弱耦合 | 生成引擎不知道文件版本；ContentGenerator 不讀 DocumentVersion |
| README ↔ 實際狀態 | ⚠️ 過時 | README 路線圖把 P10/P11 列為未完成，但 P12/P13 已納入程式碼 |

---

## 五、SaaS → 地端轉型清理清單 (Phase 9)

Phase 9 聲稱已完成 SaaS 到地端轉型，但以下 SaaS 產物仍殘留：

| 項目 | 位置 | 用途 | 地端是否需要 |
|---|---|---|---|
| `Tenant.plan` / `Tenant.max_users` | models/tenant.py | SaaS 方案管理 | ❌ |
| `Tenant.monthly_query_limit` / `monthly_token_limit` | models/tenant.py | SaaS 配額 | ❌ (但可轉用為地端使用上限) |
| analytics.py (跨 tenant 分析) | endpoints/analytics.py | SaaS 全平台監控 | ❌ |
| FeatureFlag `allowed_tenant_ids` | models/feature_flag.py | SaaS 多租戶特性開關 | ❌ (地端單組織不需要) |
| SSO (Google/Microsoft OAuth) | schemas/sso.py + migration | SaaS SSO | ⚠️ 可選 |
| 白標品牌欄位 | t4_3_branding migration | SaaS 白標 | ❌ |
| 多區域欄位 | t4_19_multi_region migration | SaaS 多區域 | ❌ |
| `CustomDomain` | migration | SaaS 自訂域名 | ❌ |

---

## 六、架構一致性問題摘要

### 6.1 命名慣例不一致

| 面向 | Phase 1-8 | Phase 10 | Phase 11-13 |
|---|---|---|---|
| tenant 欄位 | `tenant_id` + FK | `org_id`，無 FK | `tenant_id` + FK |
| table 命名 | 自動小寫 (`auditlogs`) | 底線 (`watch_folders`) | 混合 |
| DateTime | `DateTime(timezone=True)` | `DateTime` (無 tz) | `DateTime(timezone=True)` |
| default 時間 | `server_default=func.now()` | `default=datetime.utcnow` | `server_default=func.now()` |
| relationship | 完整宣告 | 零宣告 | 部分 (backref) |
| CRUD 層 | 獨立 crud_xxx.py | 無 (inline ORM) | 無 (inline ORM) |
| Schema | 獨立 schemas/xxx.py | inline Pydantic | 獨立 schemas/ |
| Auth guard | `Depends(get_current_active_user)` | 手動 `_admin_only()` | 手動 `_require_admin()` |

### 6.2 缺失的關係連結 (Relationship Gap)

以下 FK 存在但缺少 ORM `relationship()`：

| Model | 缺失的 relationship |
|---|---|
| ChatFeedback | tenant, message, user (全部 3 個 FK) |
| ReviewItem | watch_folder, reviewer, document (全部 3 個 FK) |
| KBBackup | tenant, initiated_by (全部 2 個 FK) |
| KnowledgeGap | tenant, resolved_by, resolved_document (全部 3 個 FK) |
| IntegrityReport | tenant |
| AuditLog | actor_user |
| RetrievalTrace | tenant, conversation |
| DocumentChunk | tenant |
| DocumentVersion | uploaded_by, tenant |
| CategoryRevision | actor_user, tenant |

---

## 七、建議修復順序

### 第一優先 (阻塞部署 — 1-2 天)

| 順序 | 工作項 | 對應缺陷 |
|---|---|---|
| 1 | 合併雙 migration 目錄，修正表名 bug | C-02 |
| 2 | 產生 P13 六張表的 migration | C-01 |
| 3 | WatchFolder/ReviewItem 改 `tenant_id` + FK | C-03 |
| 4 | 修正 Category 自參照 relationship | C-04 |
| 5 | 修正 AuditLog/DocumentChunk schema 欄位名 | C-09, C-10 |

### 第二優先 (功能修復 — 2-3 天)

| 順序 | 工作項 | 對應缺陷 |
|---|---|---|
| 6 | companyApi 路徑修正 + 補齊 5 個缺失 endpoint | C-05 |
| 7 | Mobile SSE 型別對齊 + ChatSource 修正 | C-06, C-07 |
| 8 | generate.py Document 參照修正 + templates 加認證 | C-08, C-13 |
| 9 | Chat route 順序修正（search 移前） | C-11 |
| 10 | Agent 審核加 tenant 檢查 | C-14 |
| 11 | KnowledgeGap FK 加上 | C-12 |

### 第三優先 (品質加固 — 3-5 天)

| 順序 | 工作項 | 對應缺陷 |
|---|---|---|
| 12 | Phase 10 DateTime timezone 統一 | H-01 |
| 13 | Token 到期 / 費率 從 config 讀取 | H-02, H-03 |
| 14 | 角色檢查補齊 (category CRUD, health, feedback/stats) | H-05, H-06, H-12 |
| 15 | generate.py 加 usage logging | H-04 |
| 16 | analytics.py SaaS 殘留清理 | H-09 |
| 17 | mobile.py 加 prefix `/mobile` | H-07 |
| 18 | ProgressDashboard 死連結修正 | H-08 |
| 19 | README 路線圖更新 | H-19 |

---

## 八、產品經理結語

這套系統的**核心 RAG pipeline (Phase 3-6) 工程品質紮實**，混合檢索、重排序、串流問答、多輪對話都有完整實作。Phase 1-8 之間的整合度也相當高，權限管理、稽核日誌、部門隔離都互相連貫。

**但 Phase 9-13 (Enclave 延伸) 的整合品質明顯下滑**：

1. **Phase 10 (Agent)** 像是獨立開發後拼裝進來的 — `org_id`/`tenant_id` 命名分裂、DateTime 格式不同、零 relationship、inline-ORM 全部偏離原有 Pattern，這說明 Phase 10 的開發者可能沒有深入理解 Phase 1-8 的慣例。

2. **Phase 11 (生成)** 參照了不存在的 Document 欄位 (`content`, `title`)，說明開發時可能是先寫了端點，但沒有回頭確認 Model 定義。

3. **Phase 12 (Mobile)** 的 SSE 型別完全與後端格式不吻合，明確指出前後端沒有對齊過通訊協議。

4. **Phase 13 (維護)** 功能邏輯最完整，但最基本的 migration 都缺，部署後必定 crash。

5. **Migration 管理** 是最嚴重的系統性問題 — 雙目錄衝突意味著即使修好了程式碼，資料庫也無法正確初始化。

**一句話總結**: Phase 1-8 是一個有完成度的產品骨架，Phase 9-13 是功能正確但整合不到位的擴展。在修復上述 14 項必修缺陷之前，這套系統**不具備對外部署的條件**。修復工作量預估 7-10 個工程天，不需要重構，只需要嚴格對齊。
