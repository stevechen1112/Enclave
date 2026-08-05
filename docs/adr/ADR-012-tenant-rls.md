# ADR-012：PostgreSQL Row-Level Security 租戶硬隔離

**狀態**：已接受
**日期**：2026-08-04
**決策者**：Enclave 技術團隊
**關聯**：`CLOUD_AND_COMMERCIALIZATION_PLAN.md` §5.2（WS-RLS）；ADR-003 v2 原則 8；參照 UniHR `t8_1_tenant_rls.py`／`RLS_ROLLOUT_PLAN.md`

---

## 背景

Enclave 的租戶隔離目前完全依賴**應用層**：ORM 查詢帶 `tenant_id` WHERE＋Resource PEP。ADR-003 v1 當年明確「不引入實體 DB 隔離」。這在單客戶地端足夠，但形態 C（多租戶 SaaS）下，任何一個應用層 bug（漏加 filter、raw SQL、背景任務忘記帶 context）都會變成跨租戶資料洩漏——**爆炸半徑從「一個客戶的資料」變成「所有客戶的資料」**。

UniHR 已實作 PG RLS（`app.tenant_id` GUC＋policy＋分階段 rollout 開關），證明此模式在 FastAPI／SQLAlchemy／Celery 架構可行。

## 決策

**形態 C 啟用 PostgreSQL Row-Level Security 作為租戶邊界的最後一道防線；應用層 PEP 不變，RLS 是補強不是取代。**

### 具體措施

1. **Policy 範圍**：所有含 `tenant_id` 的核心表啟用：
   ```sql
   ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
   ALTER TABLE <t> FORCE ROW LEVEL SECURITY;  -- 連 table owner 也受約束
   CREATE POLICY tenant_isolation ON <t>
     USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
     WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
   ```
2. **連線 context**：`app/services/rls.py` 提供 `apply_rls_context(db, tenant_id)`，在每個 request／task 的 session 開始時 `SET LOCAL app.tenant_id`（transaction-scoped，避免連線池殘留）。
3. **平台超管通道**：獨立 DB 角色或 `SET LOCAL app.bypass_rls = on` 的 bypass policy，**僅**平台維運任務（跨租戶彙總、migration）可用；應用程式碼預設不得使用。
4. **分階段 rollout**（嚴謹性要求）：
   - `RLS_ENFORCEMENT_ENABLED=false`（預設）：policy 建立但不啟用 FORCE，僅 shadow 記錄「若啟用會被擋的查詢」。
   - shadow 期間：所有 request／task 都設定 context，比對「實際結果集」與「RLS 模擬結果集」的差異並記 log。
   - 差異連續 14 天為零＋繞過測試全綠 → 才允許 `RLS_ENFORCEMENT_ENABLED=true`。
5. **邊界限定**：RLS **只做租戶邊界**；部門 ACL、文件級 PEP 維持在應用層（不下沉，避免 policy 爆炸與效能問題）。
6. **Celery／背景任務**：所有 task 入口強制經 context middleware；未設 context 的 task session 預設**看不到任何租戶列**（fail-closed，不是 fail-open）。

### 明確不做事項

- 不做 schema-per-tenant 或 database-per-tenant（營運複雜度不成比例）。
- 不把部門／文件 ACL 下沉為 RLS policy。
- 形態 A／B 預設**不啟用**（單租戶實例無需求），但程式必須永遠正確設定 context（讓 C 形態可隨時開啟）。

### 硬性部署前提（2026-08-04 實測發現）

**RLS 對 superuser 與 `BYPASSRLS` 角色完全無效**（PG 原生行為，FORCE 也擋不住）。
`tests/test_rls.py` 的 live 攻擊測試證實：以 superuser 連線時跨租戶列全部可見；
改用非 superuser 角色後 policy 才生效。因此 enforce 階段必須滿足：

1. 應用程式 DB 角色為**非 superuser、無 BYPASSRLS 屬性**的專用帳號（如 `enclave_app`）。
2. migration／維運另用高權限帳號，與應用連線分離。
3. CG-RLS 閘門檢查：`SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user` 必須皆為 false。

### 交易邊界（2026-08-04 code review 發現）

`set_config(..., is_local=true)` 隨 transaction 結束消失，而應用在單一 request／task
內會多次 commit。`rls.py` 以 SQLAlchemy `after_begin` 監聽器從 `session.info`
自動重設 context（live 測試 `test_sqlalchemy_context_survives_commit` 實證）。
**任何繞過 `apply_rls_context`／`task_session` 自行操作 GUC 的程式都視為 defect。**

## 理由

1. **縱深防禦**：應用層 bug 不再等於跨租戶洩漏——資料庫是最後一道牆。
2. **UniHR 實證模式**：同一框架組合（FastAPI＋SQLAlchemy＋Celery）已跑通，直接移植其 rollout 紀律。
3. **fail-closed 預設**：忘記設 context 的結果是「看不到資料」（可發現、可修復），不是「看到全部」（災難）。

## 後果

- 所有 DB session 取得點需接 `apply_rls_context`；遺漏處在 enforce 後會查無資料（測試必須覆蓋）。
- 新增表若含 `tenant_id`，migration 必須同時建 policy（寫入 migration 檢查清單／CI 靜態掃描）。
- 測試要求（CG-RLS 閘門）：
  1. 偽造 JWT tenant_id 的請求拿不到他租戶資料（應用層＋RLS 雙重）
  2. raw SQL（繞過 ORM）仍受 policy 約束
  3. Celery task 未設 context → 查詢回空
  4. bypass 角色僅限平台維運帳號
  5. shadow 差異率報告為零才可轉 enforce
