# P5 效能、容量、成本與穩定性模型

`config/capacity_profiles.json` 是 Lite、Standard、Enterprise 容量假設的唯一權威來源。部署說明、負載 runner、遙測採樣器與 `P5-CAPACITY` gate 必須讀取同一份檔案，不可各自維護一組數字。

## Profile 定位

| Profile | 基準硬體 | 預估尖峰並行 | 預估尖峰 RPM | 每日媒體處理量 |
|---|---:|---:|---:|---:|
| Lite | 4 CPU / 8 GB RAM | 20 | 240 | 2 小時 |
| Standard | 8 CPU / 32 GB RAM / 8 GB VRAM | 100 | 1,200 | 12 小時 |
| Enterprise | 16 CPU / 64 GB RAM / 24 GB VRAM | 500 | 6,000 | 60 小時 |

這些是內部驗證起點，不是尚未證實的對客承諾。每一種 profile 都必須在對應資源邊界中完成至少 15 分鐘、預估尖峰 2 倍的 live capacity run，才能產生該 profile 的 capacity report。

## 必測 workload

登入、資產列表、知識搜尋、有來源問答、文件上傳、批次 ingestion、音訊 queue 與影片 queue 全部是 gate 的必要情境。只測健康檢查或讀取 API 不算完成。

## 必收遙測

每次 run 必須同時保留 API latency/error、DB pool、Redis memory、Celery backlog、object I/O、process memory、CPU、provider latency/error。容量報告至少 15 個樣本；72 小時 soak 以五分鐘為上限間隔，樣本完整率至少 95%。

## 成本單位與護欄

內部成本模型固定輸出每租戶、每 GB-month、每小時音訊、每小時影片與每千次問答。設定的單價是預算基準，可由部署設定覆寫；報告必須保留實際 provider 帳單或本地算力估算來源。超限時必須阻擋新的高成本工作或明確降級，不得只告警後繼續無上限消耗。

## 降級契約

- provider 變慢：有限 timeout／retry，回傳 pending 或可恢復失敗，不可假完成。
- quota 用盡：回傳結構化 429，保留既有資料與唯讀能力。
- queue 飽和：拒絕或延後新工作並提供 retry-after；不可讓 backlog 無界增長。
- sidecar unavailable：核心知識與權限邊界持續有效；相依功能顯示 disabled／degraded。

## Gate 誠信

`scripts/verify_p5_capacity.py` 只驗證 evidence，不產生 evidence。它會檢查 profile 規格雜湊、真實時間跨度、2 倍目標、必要情境、遙測完整性、資料一致性、成本護欄及四種降級測試。72 小時未實際經過或樣本不足時結果只能是 `HOLD`。

## 隔離 staging 執行順序

所有 runner 都只能對專用測試租戶與隔離 staging 執行；不得拿 production
`/opt/enclave` 當壓測或故障注入目標。密碼只透過環境變數或命令參數注入，
不得寫入 evidence、plan 或 Git。

1. 以 `scripts/run_p5_capacity.py` 依序執行 Lite、Standard、Enterprise；每次至少
   900 秒並使用 profile 定義的 2× 並行數。`--integrity-evidence` 必須來自同一次
   run 後的租戶隔離與 job reconciliation live probe。Runner 會實測 CPU、RAM、
   disk 與 GPU VRAM；主機低於該 profile 基準時會在負載開始前 fail-fast，不能用
   Lite 主機產生 Standard 或 Enterprise 的報告。
2. 以 `scripts/run_p5_cost_guardrails.py` 對專用測試租戶暫時收緊成本上限，驗證
   問答在預估超額前回傳 cost-axis 429，並在 `finally` 恢復原配額。
3. 為 `provider_slow`、`quota_exhausted`、`queue_saturated`、
   `sidecar_unavailable` 各準備一份 command plan，交給
   `scripts/run_p5_degradation.py`。Plan 的 baseline／inject／probe／recover／verify
   都是 argv array，不經 shell；verify 必須輸出 `data_loss=0` 與
   `false_completion=0` 的 JSON。
4. 容量與降級短測通過後，才以 `scripts/run_p5_soak.py` 啟動 Standard profile
   的 1× 預估尖峰 72 小時測試。Runner 拒絕任何短於 259,200 秒的正式 run。
5. 以 `scripts/assemble_p5_evidence.py` 組合三份 capacity report、soak report、
   cost report、四份 degradation report、source commit 與 runtime image IDs。
   組裝器只引用既有 artifact；缺少任何一項時輸出 `HOLD` 並以非零狀態結束。
6. 最後以 `scripts/verify_p5_capacity.py` 對組裝結果獨立重驗。只有 `PASS` 才能
   進入 P5 Code Review。

Soak 的負載契約刻意與容量測試分開：capacity 使用 2× 尖峰；soak 使用 1×
預估尖峰。兩者都由同一份容量規格產生，report 不得混用 execution class 或
multiplier 標記。
