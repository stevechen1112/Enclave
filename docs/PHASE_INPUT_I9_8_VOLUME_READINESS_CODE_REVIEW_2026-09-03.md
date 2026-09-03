# Input I9-8 高量複測準備 Code Review

日期：2026-09-03  
範圍：正式 Provider 可用性、獨立 Input queue admission guard、第二輪租戶複測前容量檢查

## 結論

`PASS FOR DEPLOYMENT`。

本次修正沒有提高媒體並行度，而是讓既有單工 Input worker 在大量來源下可靠排隊，並確保全域 queue guard 不會漏算獨立文件及媒體 queue。這符合目前 8 GiB 級主機的穩定性邊界。

## Review 檢查

1. `check_queue_capacity()` 同時計算 `celery`、`input.document` 與 `input.media`，總深度仍沿用既有 deployment profile 上限。
2. Redis 無法讀取時維持既有 durable-ingestion fail-open 行為，沒有因監控故障直接丟棄已授權請求。
3. 飽和時維持 HTTP 503、`Retry-After` 與白話訊息，並新增各 queue 深度供維運判斷；沒有回傳租戶內容或憑證。
4. 現有 API 呼叫契約相容：既有 `allowed/state/depth/limit` 欄位不變，只增加 `queue_depths`。
5. 新增測試直接覆蓋「預設 queue 為空、獨立媒體 queue 已滿」的原漏網情境。
6. 真實 Provider probe 證明 Gemini 403，不能以設定存在代替運作驗證；改用已通過的 OpenAI 既有憑證，不需新增或輸出 API Key。
7. 未改動租戶內容、人工審核決定、原始上傳檔或知識發布狀態。

## 驗證

- `pytest -q tests/test_p5_queue_guardrails.py tests/test_input_i9_worker_isolation.py tests/test_input_i9_worker_recovery_unit.py tests/test_ingestion_failures.py`：11 passed。
- `ruff check`：pass。
- `git diff --check`：pass。
- 生產部署後必要 gate：7 條 Provider 真實呼叫、三條 queue 深度、容器 health／restart／OOM、正式網域登入與 Input capabilities。

## 殘餘風險

- 目前 Input worker concurrency 1 是刻意的可靠性設定；大量影片會增加等待時間，但不應以提高並行度換取再次 OOM 的風險。
- Cloud OCR 供應商切換後仍須以正式 probe 及第二輪真實掃描件驗證品質；Provider 可連通不等同每種影像品質都能正確辨識。
- 租戶第二輪結果尚未產生，因此本 review 只允許部署，不代表租戶驗收完成。
