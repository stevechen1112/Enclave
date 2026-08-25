# Enclave 負載測試（T4-14）

提供 Locust（Python）與 k6（JS）兩套工具，對 **Enclave API**（預設 `http://localhost:8000`）做壓力測試。

## 快速開始

### Locust

```bash
pip install locust

locust -f tests/load/locustfile.py --host=http://localhost:8000
# UI: http://localhost:8089

locust -f tests/load/locustfile.py --host=http://localhost:8000 \
       --headless -u 100 -r 10 --run-time 5m \
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
| 一般員工 | 70% | 聊天、查文件、搜尋 |
| HR | 20% | 上傳、用量相關 |
| 管理員 | 10% | 儀表板、系統健康 |

請先在目標環境建立帳號（本機 Pilot 可用 `scripts/ensure_ux_test_users.py`）。

## 效能基準線（參考）

| 端點 | P95 | P99 | 最大錯誤率 |
|------|-----|-----|------------|
| auth_login | 500ms | 1000ms | 1% |
| chat_send | 3000ms | 5000ms | 2% |
| document_list | 300ms | 600ms | 1% |
| kb_search | 1000ms | 2000ms | 2% |
| admin_dashboard | 500ms | 1000ms | 1% |
| health_check | 100ms | 200ms | 0% |

## 環境變數

對齊本機 Pilot 帳號範例：

```bash
export LOAD_TEST_ADMIN_EMAIL=admin@example.com
export LOAD_TEST_ADMIN_PASSWORD=<injected-test-secret>
export LOAD_TEST_USER_EMAIL=employee@example.com
export LOAD_TEST_USER_PASSWORD=employee123
# 若腳本仍讀 SUPERUSER，可與 admin 相同或使用 admin@enclave.local
export LOAD_TEST_SUPERUSER_EMAIL=admin@example.com
export LOAD_TEST_SUPERUSER_PASSWORD=<injected-test-secret>
```

## 結果目錄

輸出至 `tests/load/results/`（Locust CSV、k6 summary 等）。

## 瓶頸檢查方向

DB 連線池、Celery 堆積、API P95、Redis、記憶體。詳見根目錄 `README.md` 架構說明。
