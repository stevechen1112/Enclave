# Enclave P5 負載與容量測試

`config/capacity_profiles.json` 是 Lite／Standard／Enterprise 的唯一容量規格。
Locust 是 P5 完整情境 runner；k6 保留為讀取／問答 smoke，不可單獨用來通過 P5 gate。

## 快速開始

### Locust

```bash
pip install locust

set CAPACITY_PROFILE=standard
set LOAD_MULTIPLIER=2
set P5_FULL_SCENARIO=true
set LOAD_DOCUMENT_FIXTURE_PATH=C:\fixtures\capacity.txt
set LOAD_AUDIO_FIXTURE_PATH=C:\fixtures\capacity.wav
set LOAD_VIDEO_FIXTURE_PATH=C:\fixtures\capacity.mp4
locust -f tests/load/locustfile.py --host=http://localhost:8000
# UI: http://localhost:8089

locust -f tests/load/locustfile.py --host=http://localhost:8000 \
       --headless -u 200 -r 10 --run-time 15m \
       --csv=tests/load/results/report
```

### k6

```bash
k6 run tests/load/k6_load_test.js

k6 run tests/load/k6_load_test.js \
  --env BASE_URL=http://localhost:8000 \
  --env VUS=100 --env DURATION=5m
```

## 測試情境（角色比例）

| 角色 | 比例 | 行為 |
|------|------|------|
| 知識使用者 | 82% | 資產列表、搜尋、有來源問答 |
| Ingestion 管理員 | 9% | 文件、batch、音訊與影片 queue |
| 平台管理員 | 9% | 健康與營運可視性 |

請先在目標環境建立帳號（本機 Pilot 可用 `scripts/ensure_ux_test_users.py`）。

## 效能基準線

端點 SLO 依 `CAPACITY_PROFILE` 從容量規格載入。所有 profile 的正式容量測試都必須達到其預估尖峰 2 倍、至少 15 分鐘，並同時由 P5 telemetry collector 留下資源樣本。

## 環境變數

對齊本機 Pilot 帳號範例：

```bash
set LOAD_TEST_ADMIN_EMAIL=admin@example.com
set LOAD_TEST_ADMIN_PASSWORD=<injected-test-secret>
set LOAD_TEST_USER_EMAIL=employee@example.com
set LOAD_TEST_USER_PASSWORD=<injected-test-secret>
set LOAD_TEST_SUPERUSER_EMAIL=admin@example.com
set LOAD_TEST_SUPERUSER_PASSWORD=<injected-test-secret>
```

## 結果目錄

輸出至未納入版本控制的 evidence 工作目錄；正式執行應使用
`scripts/run_p5_capacity.py`，由 runner 綁定 source commit、image identity、規格雜湊與遙測輸出。

## 瓶頸檢查方向

DB 連線池、Celery 堆積、API P95、Redis、記憶體。詳見根目錄 `README.md` 架構說明。
