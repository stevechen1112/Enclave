# Staging 與 Rollback Runbook（職能任務平台重構期間適用）

> 原則：**不得直接在 kachu.tw（生產）開發或熱改**。所有重構變更先在本地與 staging 驗證，再依發佈順序上線。

## 環境分層

| 環境 | 位置 | 用途 | 資料 |
|------|------|------|------|
| local | 開發機（host API :8005 + docker db/redis） | 日常開發、單元/契約測試、gates | 可隨時重建 |
| staging | Linode 同機獨立 compose project（`enclave-staging`）或獨立 VM | migration dry-run、dual-run、上線前驗收 | 生產備份還原的脫敏副本 |
| production | https://kachu.tw（`docker-compose.prod.yml`） | 對外服務 | 真實資料，僅能透過發佈流程變更 |

## 發佈前檢查清單（每次必做）

1. **基線閘門**：`python scripts/mka_progress_gate.py --all` 全綠（目前基線 28/28）。
2. **DB 備份**（生產或 staging 升級前）：

   ```bash
   ./scripts/db_backup.sh --compose docker-compose.prod.yml --env .env.production
   ```

3. **Migration dry-run**：先看 SQL 再執行。

   ```bash
   ./scripts/migration_dryrun.sh --compose docker-compose.prod.yml --env .env.production
   # 審閱 artifacts/migration_dryrun_<ts>.sql
   ```

4. **N-1 相容**：新版本程式必須能在「舊 schema」與「新 schema」各跑過一次 smoke
   （先部署程式碼、再跑 migration 的順序必須可行；反之亦然）。
5. **Feature flag**：新功能一律以 flag 包住（如 `TASK_ENGINE_ENABLED`），預設關閉，
   逐租戶開啟。flag 關閉時行為必須與舊版完全一致。

## Staging 操作

```bash
# 在 Linode 主機上（staging 用獨立 project 名避免與生產互踩）
cd /opt/enclave
docker compose -p enclave-staging -f docker-compose.prod.yml --env-file .env.staging up -d

# 還原生產備份到 staging DB（先確認 staging 無重要資料）
gunzip -c backups/enclave_<ts>.sql.gz | \
  docker compose -p enclave-staging -f docker-compose.prod.yml exec -T db \
  psql -U postgres -d enclave

# staging 上跑 migration
docker compose -p enclave-staging -f docker-compose.prod.yml exec -T web alembic upgrade head
```

## Rollback 程序

1. **程式碼回滾**：重新部署前一個 git tag 的映像（`deploy_linode.sh` 會記錄部署的 commit）。
2. **DB 回滾**：
   - 優先 `alembic downgrade <prev_revision>`（每個 migration 必須實作可逆的 `downgrade()`）。
   - 若 downgrade 不可行（如破壞性欄位移除），還原升級前的備份：

     ```bash
     docker compose -f docker-compose.prod.yml --env-file .env.production stop web worker worker-beat
     gunzip -c backups/enclave_<升級前ts>.sql.gz | \
       docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db \
       psql -U postgres -d enclave
     docker compose -f docker-compose.prod.yml --env-file .env.production up -d
     ```

3. **Feature flag 回滾**：把新功能 flag 關閉即可即時回退到舊路徑，不需重新部署。
4. **驗證**：rollback 後跑 `scripts/verify_deployment.sh` 確認服務健康。

## Rollback rehearsal（每個 Phase 上線前）

- 在 staging 完整演練一次「升級 → 驗證失敗 → rollback → 驗證恢復」，
  並把耗時與結果記錄在 `docs/reports/`。
