# P5 Live Degradation Drill Runbook

本 runbook 只適用於 environment evidence 已為 `PASS` 的獨立 staging。若 Docker host
同時存在 production 或其他 Enclave Compose project，plan generator 與 runner
都必須停止，不可覆寫 HOLD。

## 安全契約

- `provider_slow`：暫停受測 Compose project 的 embedding provider；新工作只能
  保持 pending／running，不得假完成，恢復 provider 後必須完成。
- `quota_exhausted`：暫時降低測試租戶 cost quota；問答必須回傳 cost-axis 429，
  finally/recover 必須精確還原原配額。
- `queue_saturated`：先暫停受測 worker，再以唯一 marker 填滿 Celery queue；新
  intake 必須回傳 503、`queue_saturated` 與 `Retry-After`。恢復只刪除本次 marker，
  不得清空整條 queue。
- `sidecar_unavailable`：暫停指定 sidecar；gateway 必須揭露 unavailable／degraded，
  核心 Enclave 搜尋與租戶權限仍須可用，sidecar 恢復後 health 必須復原。

每個情境先建立一個 control ingestion。恢復後，driver 會在同一 release worker 中
執行 `run_p5_integrity_probe.py`，實測 RLS、公開 API 跨租戶 404、canonical asset／
revision／document／chunk 一致性，以及本次 run 所有 ingestion job reconciliation。

## 前置資料

準備以下檔案，且全部只放在專用 staging artifact 目錄：

- PASS environment evidence。
- 與 runtime source commit 一致的 grounded evidence。
- 同一租戶的 token credential pool；權限設為 0600。
- 小型合成文件 fixture，不得使用客戶資料。

管理者密碼只以 `P5_ADMIN_PASSWORD` 環境變數注入。不得把 password、token、API key
或 Authorization header 寫入 plan、argv、Git 或 transcript。

## 產生四份 plans

```bash
export P5_ADMIN_PASSWORD='<injected by secret manager>'

python scripts/prepare_p5_degradation_plans.py \
  --environment-evidence artifacts/ops/p5/environment-evidence.json \
  --output-dir artifacts/ops/p5/degradation \
  --base-url https://p5-staging.example.com \
  --tenant-id '<dedicated-tenant-uuid>' \
  --email '<dedicated-superuser-email>' \
  --fixture tests/load/fixtures/p5_grounded_sop.md \
  --credentials artifacts/ops/p5/token-pool.json \
  --grounding-evidence artifacts/ops/p5/grounding-evidence.json \
  --provider-service ollama-embed \
  --sidecar-key ragflow \
  --sidecar-service ragflow
```

Generator 會鎖定 source commit、Compose project、driver 與 integrity probe hash。
任何 working-tree 差異、缺少 trusted file 或 shared-host evidence 都會 fail closed。

## 逐一執行

四種情境必須串行，不可同時注入：

```bash
python scripts/run_p5_degradation.py \
  --plan artifacts/ops/p5/degradation/provider_slow.plan.json \
  --environment-evidence artifacts/ops/p5/environment-evidence.json \
  --output artifacts/ops/p5/degradation/provider_slow.report.json \
  --timeout-seconds 1200 \
  --confirm-isolated-staging
```

依序將 plan／output 換成 `quota_exhausted`、`queue_saturated` 與
`sidecar_unavailable`。每次都必須得到 `execution_class=live`、`status=PASS`、
`data_loss=0`、`false_completion=0`、`cross_tenant_leak=0` 與 `recovered=true`。

## 中斷與復原

Outer runner 無論 baseline、inject 或 probe 是否失敗，都會嘗試 recover 與 verify。
若 SSH 或 runner 程序在注入期間被外力終止，直接以同一份 plan 再執行一次 runner；
baseline 會拒絕未完成 state，runner 隨後仍會執行該 state 對應的 recover。這次重跑
應視為 FAIL／recovery evidence，不可冒充正式 PASS；確認容器皆未 paused、quota
已還原、queue 回到 baseline 後，再使用全新的 artifact 目錄重跑正式情境。

禁止使用 `docker compose down`、`FLUSHDB`、清空 Celery queue 或修改 production
來處理 drill 中斷。Queue recovery 只能刪除 state 中記錄的唯一 marker。
