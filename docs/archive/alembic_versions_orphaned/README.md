# 已歸檔：無效 Alembic versions（舊審計 C-02）

**歸檔日期**：2026-08-01  
**原因**：`alembic.ini` 的 `script_location = app/db/migrations`，本目錄下的檔案**永遠不會被執行**，易造成「以為 migration 會跑」的部署踩坑。

## 覆蓋確認

以下表已由正式鏈 `app/db/migrations/versions/` 涵蓋（含 `d1e2f3a4b5c6_phase10_13_tables.py`、後續 gateway／quota 等）：

| 表／主題 | 正式鏈 |
|----------|--------|
| `watch_folders` / `review_items` | ✅ |
| `chat_feedbacks` | ✅ |
| `documentversions` / `categories` / … | ✅ |
| `custom_domains` / feature flags / SSO | ✅ |
| gateway／connector／wiki／graph／quota 等 | ✅（見 `python -m alembic history`） |

## 歸檔檔案

- `p10_watch_folders_and_review_items.py`
- `t7_5_feedback.py`
- `t4_3_branding.py`
- `t4_6_custom_domain.py`
- `t4_15_db_indexes.py`
- `t4_19_multi_region.py`

**勿**把這些檔案移回 `alembic/versions/` 當作正式 migration。若需參考歷史 SQL，只讀本目錄。

本機清空重建請用根目錄 `README.md` §6.3（對 `app/db/migrations` 跑 `alembic upgrade head`）。
