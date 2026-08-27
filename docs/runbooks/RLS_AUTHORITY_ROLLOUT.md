# Knowledge Authority RLS 上線 Runbook

## 安全預設

`RLS_ENFORCEMENT_ENABLED=false` 只建立並啟用 tenant policy，不執行 `FORCE ROW LEVEL SECURITY`。`KNOWLEDGE_UNIT_READ_MODE=shadow` 保留 legacy answer path，canonical read 只做比較與紀錄。

不得因 migration、測試或本文件存在，就宣稱 14 天觀察條件已完成。

## Shadow gate

每個 production tenant 至少連續 14 天保存以下證據：

- KnowledgeUnit sealed parity 無未解釋 mismatch。
- API、Celery、maintenance command 全部以明確 tenant context 執行。
- 專用 application role 必須是 `NOSUPERUSER NOBYPASSRLS`。
- `tests/test_rls.py` 的 live PostgreSQL attack tests 通過。
- `python scripts/knowledge_authority_gate.py` 回傳 `ready_for_shadow`，且 active release 無重複。
- 已演練 read mode 與 RLS 的個別回滾，並保留操作者、時間、版本與結果。

資料庫連線設定必須使用 `POSTGRES_SERVER`、`POSTGRES_PORT`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB`；目前 Alembic 不讀單一 `DATABASE_URL`。

## Enforce 順序

1. 先將測試租戶的 `KNOWLEDGE_UNIT_READ_MODE` 切到 `enforce`，確認只有 active release membership 可回答。
2. 逐租戶 canary；禁止一次切換所有租戶。
3. 以 migration runner 設 `RLS_ENFORCEMENT_ENABLED=true`，重新套用 policy/force migration 或受控 DDL。
4. application API、worker、scheduler、backfill 均使用非 superuser role 驗證。
5. 觀察拒答率、零結果率、ACL deny、parity 與 worker failure。

## 回滾

先將 `KNOWLEDGE_UNIT_READ_MODE=shadow` 恢復 legacy serving，再將新 authority tables 設為 `NO FORCE ROW LEVEL SECURITY`。不得刪除 SourceAsset、KnowledgeUnit revision、release 或 evidence；回滾只改 serving mode 與 enforcement，保留稽核鏈。若需 schema downgrade，先確認沒有僅存在新權威、尚未投影回 legacy 的資料。
