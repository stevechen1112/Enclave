# Pilot Support Runbook

**產品**：Enclave Triple Injection Pilot  
**對象**：單一客戶地端部署  
**最後更新**：2026-08-01

## 1. 安裝（Lite / Standard）

```bash
# Lite：僅 Enclave core
docker compose -f docker-compose.profiles.yml --profile lite up -d

# Standard：+ RAGFlow / PipesHub / WeKnora（內部 expose，不對外）
docker compose -f docker-compose.profiles.yml --profile standard up -d
```

必要環境變數：

- `SECRET_KEY`
- `POSTGRES_*` / Redis
- `RAGFLOW_ENABLED=true`、`RAGFLOW_BASE_URL`、`RAGFLOW_API_KEY`、`RAGFLOW_DATASET_ID`
- `PIPESHUB_ENABLED`（可選）、`PIPESHUB_BASE_URL=http://pipeshub-api:3000`、`PIPESHUB_API_KEY`
- `WEKNORA_ENABLED`（可選）、`WEKNORA_BASE_URL=http://weknora:8080`、`WEKNORA_API_KEY`
- 生產建議：`MTLS_CLIENT_CERT` / `MTLS_CLIENT_KEY` / `MTLS_CA_CERT`

Preflight / 一鍵生命週期（Windows 友善）：

```bash
python scripts/preflight_check.py --profile lite
python scripts/ops_lifecycle.py preflight --profile lite
python scripts/ops_lifecycle.py backup
python scripts/ops_lifecycle.py upgrade --revision head
python scripts/ops_lifecycle.py rollback --steps 1
python scripts/ops_lifecycle.py install --profile lite
python scripts/ops_lifecycle.py remove --profile lite
```

產物寫入 `artifacts/ops/`。現場簽核仍需人工完成。

健康檢查：

```bash
curl -f http://localhost:8000/health
curl -f http://localhost:9380/api/v1/system/healthz   # 僅開發主機可達時
```

## 2. Pilot 垂直切片驗收

```bash
set RAGFLOW_ENABLED=true
set RAGFLOW_FORCE_PARSE=true
python scripts/e2e_vertical_slice_full.py
```

通過條件：`artifacts/pilot_e2e_last_run.json` 的 `status` 必須為 `PASS`。

## 3. 備份

```bash
# PostgreSQL
docker compose -f docker-compose.profiles.yml exec -T db pg_dump -U postgres enclave > backup_$(date +%Y%m%d).sql

# 上傳目錄
tar -czf uploads_$(date +%Y%m%d).tgz uploads/
```

還原：

```bash
cat backup_YYYYMMDD.sql | docker compose -f docker-compose.profiles.yml exec -T db psql -U postgres enclave
```

## 4. 升級 / 回滾

1. 備份 DB + uploads  
2. `alembic upgrade head`  
3. 拉鎖定 tag/digest 的映像（禁止生產追 `latest` 而無 digest）  
4. 重啟 web/worker  

回滾：

```bash
alembic downgrade -1
# 並切回前一組映像 digest
```

## 5. 移除

```bash
docker compose -f docker-compose.profiles.yml --profile standard down
# 若需清除資料卷（不可逆）
docker compose -f docker-compose.profiles.yml --profile standard down -v
```

## 6. Support Bundle

```bash
# API（需 admin）
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/operations/support-bundle -o bundle.json
```

Bundle 應含：版本矩陣、服務健康、模組啟用狀態。脫敏：勿包含 raw secrets / 完整文件內容。

## 7. 常見故障

| 症狀 | 檢查 |
|------|------|
| Pilot E2E FAIL ragflow_unavailable | RAGFlow healthz、API key、dataset id |
| sync mode=local_mock | `PIPESHUB_ALLOW_MOCK` 必須 false；NAS 需 `root_path` |
| 撤權後仍搜到 | Gateway deny set、ACL epoch bump、tombstone |
| sandbox 失敗 | 勿設 `ENCLAVE_SANDBOX_SECCOMP=default`；Docker 需可用 |
| Wiki status=failed | WeKnora 未啟用或編譯失敗（不會發布占位文字） |

## 8. 人工閘門（非本 runbook 自動完成）

- 外部滲透測試  
- 模型／依賴法律授權審查  
- 真實 SharePoint / Google Drive OAuth 客戶端認證  
- 客戶現場災難復原演練簽核  
