# Enclave 負載測試 (T4-14)

## 工具選擇

提供兩套負載測試工具，可依團隊熟悉度選擇：

| 工具 | 語言 | 適合場景 |
|------|------|----------|
| **Locust** | Python | 團隊以 Python 為主、需自訂複雜邏輯 |
| **k6** | JavaScript | 需要精確效能門檻、CI/CD 整合 |

## 快速開始

### Locust

```bash
# 安裝
pip install locust

# Web UI 模式（開發時使用）
locust -f tests/load/locustfile.py --host=http://localhost:8000
# → 開啟 http://localhost:8089 設定並啟動

# Headless 模式（CI 適用）
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
       --headless -u 100 -r 10 --run-time 5m \
       --csv=tests/load/results/report
```

### k6

```bash
# 安裝（macOS）
brew install k6

# 執行
k6 run tests/load/k6_load_test.js

# 自訂參數
k6 run tests/load/k6_load_test.js \
  --env BASE_URL=http://localhost:8000 \
  --env VUS=100 --env DURATION=5m
```

## 測試情境

### 使用者角色分佈
| 角色 | 比例 | 行為 |
|------|------|------|
| 一般員工 | 70% | 聊天、查文件、搜尋知識庫 |
| HR 管理員 | 20% | 上傳文件、查稽核、管理公司 |
| 平台管理員 | 10% | Dashboard、租戶管理、系統健康 |

### 壓力測試階段（k6）
| 階段 | 時長 | VUs | 說明 |
|------|------|-----|------|
| Warm up | 1m | 0→20 | 暖機 |
| 中負載 | 3m | 20→50 | 日常水準 |
| 高負載 | 3m | 50→100 | 尖峰水準 |
| 壓力測試 | 2m | 100→150 | 超載壓測 |
| Cool down | 1m | 150→0 | 降溫 |

## 效能基準線

| 端點 | P95 上限 | P99 上限 | 最大錯誤率 |
|------|----------|----------|------------|
| auth_login | 500ms | 1000ms | 1% |
| chat_send | 3000ms | 5000ms | 2% |
| document_list | 300ms | 600ms | 1% |
| kb_search | 1000ms | 2000ms | 2% |
| admin_dashboard | 500ms | 1000ms | 1% |
| health_check | 100ms | 200ms | 0% |
| subscription_plans | 200ms | 400ms | 1% |

## 瓶頸分析方向

測試完成後，根據結果檢查以下瓶頸：

1. **DB 連線池** — 觀察 `pool_size` / `max_overflow` 是否飽和
2. **Celery Worker** — 文件處理佇列是否堆積
3. **API 回應時間** — 哪些端點 P95 超標
4. **Redis 連線** — Rate limiter / cache miss ratio
5. **記憶體** — 大量並發下是否有 memory leak

## 環境變數

```bash
# 測試帳號（需事先在目標環境建立）
export LOAD_TEST_ADMIN_EMAIL=admin@example.com
export LOAD_TEST_ADMIN_PASSWORD=admin123
export LOAD_TEST_USER_EMAIL=user@example.com
export LOAD_TEST_USER_PASSWORD=user123
export LOAD_TEST_SUPERUSER_EMAIL=superadmin@example.com
export LOAD_TEST_SUPERUSER_PASSWORD=superadmin123
```

## 結果目錄

測試報告輸出至 `tests/load/results/`：
- `report_stats.csv` — Locust 統計
- `report_failures.csv` — 失敗紀錄
- `k6_summary.json` — k6 摘要
