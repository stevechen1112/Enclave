# Knowledge Authority 與租戶 RLS 上線 Runbook

## 安全不變條件

- `web`／一般 worker 僅使用 `POSTGRES_USER`；該登入必須是 `NOSUPERUSER NOBYPASSRLS`、不得擁有 schema。
- migration 僅使用 `DB_ADMIN_*`，不得把 owner 密碼注入 `web`／worker。
- 跨租戶 maintenance task 僅使用 `MAINTENANCE_POSTGRES_*`。此登入沒有 PostgreSQL 原生 `BYPASSRLS`，只能藉 `enclave_rls_bypass` marker role 與 `app.bypass_rls=on` 共同生效，且每次必須寫入 append-only audit。
- 備份與還原使用 `DB_ADMIN_*`；不得用受 RLS 限制的 application role 製作全庫備份。
- `RLS_ENFORCEMENT_ENABLED=false` 僅供 rollout 前 shadow。正式啟用後，所有 tenant table 必須 `ENABLE` 且 `FORCE ROW LEVEL SECURITY`。
- `KNOWLEDGE_UNIT_READ_MODE=shadow` 只比較 canonical 與 legacy serving；不得把 migration 或單次測試當成 14 天觀察證據。

## 初始建置與每次部署

三種憑證必須分檔且彼此不同：`.env.production` 只放 `POSTGRES_*`，`.env.db-admin` 只放 `DB_ADMIN_*`，`.env.maintenance` 只放 `MAINTENANCE_POSTGRES_*`。三檔權限設為 `0600`；`web` 只注入第一檔，worker 注入第一與第三檔，owner 檔只進入 DB／one-shot operations。Compose 的 interpolation 必須讀取三檔：

```bash
export COMPOSE_ENV_FILES=.env.production,.env.db-admin,.env.maintenance
docker compose -f docker-compose.prod.yml up -d db redis
docker compose --profile operations -f docker-compose.prod.yml run --rm -T migrate
docker compose --profile operations -f docker-compose.prod.yml run --rm -T provision-db-roles
docker compose -f docker-compose.prod.yml up -d --no-build --remove-orphans
```

順序不可交換：migration 先建立 policy／marker role，provision 再建立登入、授權 data plane 與收斂 audit 權限。應用服務不得執行 Alembic。

## Machine gates

在 owner/admin 連線執行 catalog 與 role gate：

```bash
python scripts/tenant_security_gate.py \
  --dsn "$P2_ADMIN_DSN" \
  --app-role "$POSTGRES_USER" \
  --maintenance-role "$MAINTENANCE_POSTGRES_USER" \
  --require-force \
  --output artifacts/security/p2_tenant_security_report.json

python scripts/tenant_session_context_gate.py \
  --output artifacts/security/p2_tenant_session_context.json
```

再以 production-like application／maintenance DSN 執行：

```bash
P2_SHADOW_REPORT_OUTPUT=artifacts/security/p2_rls_shadow_report.json \
python -m pytest tests/test_p2_rls_hard_isolation.py -q

python -m pytest \
  tests/test_p2_tenant_boundary_matrix.py \
  tests/test_p2_data_lifecycle.py \
  tests/test_tenant_session_context_gate.py -q
```

Gate 必須同時證明：所有 tenant-owned tables 已分類、100 張表有 machine-verified policy、跨租戶洩漏為 0、shadow visibility 無差異、未設 context 看不到 tenant rows、application role 無 bypass、maintenance audit 不可更新或刪除。表數增加時應同步增加，而不是把 gate 固定放寬。

## Staging FORCE rollout

1. 先以 admin 備份；`bash scripts/backup.sh --db-only` 會選用 `DB_ADMIN_*`。
2. 停止 `web`、worker、beat，避免舊程式與 FORCE schema 重疊。
3. 設定 `RLS_ENFORCEMENT_ENABLED=true`，依「初始建置與每次部署」順序 migrate、provision、啟動。
4. 驗證 API、Celery、scheduler、connector、outbox、reconciliation、audio/video ingestion、export 與 signed URL。
5. 跑完整 backend、frontend 與 browser regression；保存 test run、source commit、schema head、role gate、attack matrix、shadow report。
6. 觀察拒答率、零結果率、ACL deny、parity、worker failure 與 maintenance audit。Staging 全量回歸未 PASS 前不得進 production FORCE。

## Knowledge Authority shadow gate

每個 production tenant至少連續 14 天保存：

- KnowledgeUnit sealed parity 無未解釋 mismatch。
- API、Celery、maintenance command 全部具明確 tenant context 或 audited bypass。
- `python scripts/knowledge_authority_gate.py` 回傳 `ready_for_shadow`，且 active release 無重複。
- read mode 與 RLS 個別回滾演練的操作者、時間、版本與結果。

## 回滾

1. 先停止寫入服務並保存故障證據與 maintenance audit。
2. Knowledge Authority serving 問題：先切回 `KNOWLEDGE_UNIT_READ_MODE=shadow`，不刪 SourceAsset、KnowledgeUnit revision、release 或 evidence。
3. RLS rollout 問題：以 migration/admin 身分針對已核准範圍執行 `NO FORCE ROW LEVEL SECURITY`；不得把 web 改成 owner/superuser，也不得授予原生 `BYPASSRLS`。
4. Schema 問題：從已驗證 admin backup 還原，並確認租戶數、受保護表數、policy、row counts 與 shadow report。
5. 修復後重新通過全部 machine gates 與 staging FORCE 全量回歸，才可再次啟用。
