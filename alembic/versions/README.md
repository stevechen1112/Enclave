# DEPRECATED — Secondary Migration Directory（已清空）

本目錄**不再存放** `.py` migration 檔。

| 項目 | 說明 |
|------|------|
| 正式鏈 | `app/db/migrations/`（`alembic.ini` → `script_location`） |
| 舊殘檔 | `docs/archive/alembic_versions_orphaned/`（2026-08-01 歸檔） |
| 現行 head（示例） | 含 `p1_tenant_quota_001` 等；以 `python -m alembic heads` 為準 |

請勿在此目錄新增 migration。空庫重建流程見根目錄 `README.md` §6.3。
