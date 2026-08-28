# P5 Standard 72-Hour Soak Runbook

本程序只在三種 capacity report 與四種 degradation report 已 PASS 後執行。正式
soak 固定使用 Standard profile：8 CPU、32 GB RAM、200 GB disk、8 GB GPU VRAM，
100 concurrent users、1,200 RPM，持續至少 259,200 秒。

## 前置條件

1. Docker host 只承載受測 Enclave Compose project，不存在 production 或其他
   Enclave project。
2. Runtime `/health` 為 staging、release identifiable、source commit 與 grounded
   evidence 完全一致。
3. 準備 100 個不同使用者的唯一 access token；runner 會逐一呼叫 `/users/me`，
   確認全部 active 且屬於 grounded evidence tenant。
4. Document、audio、video 只使用合成 fixture。
5. Metrics container 必須是受測 Compose project 中 running 的 Web service；不能
   指向同機其他 container。
6. Output directory 必須是全新目錄，不能包含任何舊 soak CSV、JSONL、log 或 report。

密碼只能透過 `LOAD_TEST_USER_PASSWORD`、`LOAD_TEST_ADMIN_PASSWORD` 與
`LOAD_TEST_SUPERUSER_PASSWORD` 環境變數注入，不得寫入命令列或 evidence。

## 執行

建議在 `tmux`／`systemd-run` 等可保留程序的受控 session 執行，但 session 保留不等於
允許續接 evidence；runner 或 Locust 中斷後，正式 run 必須使用新目錄從零開始。

```bash
python scripts/run_p5_soak.py \
  --profile standard \
  --base-url https://p5-staging.example.com \
  --output-dir artifacts/ops/p5/soak-<run-id> \
  --document-fixture artifacts/ops/p5/fixtures/document.pdf \
  --audio-fixture artifacts/ops/p5/fixtures/audio.wav \
  --video-fixture artifacts/ops/p5/fixtures/video.mp4 \
  --credentials artifacts/ops/p5/standard-token-pool.json \
  --grounding-evidence artifacts/ops/p5/grounding-evidence.json \
  --metrics-container enclave-p5-web-1 \
  --compose-project enclave-p5 \
  --duration-seconds 259200 \
  --recovery-seconds 600 \
  --spawn-rate 5 \
  --confirm-isolated-staging
```

## Fail-fast 行為

- Collector 在 Locust 前死亡：立即終止 Locust，run FAIL。
- Locust 提前退出或非零：立即終止 collector，run FAIL。
- Collector 在 recovery window 未完成：terminate 後再 kill，run FAIL。
- 舊 artifact 已存在：開始前拒絕執行。
- 任一 token、租戶、release、hardware、GPU、Compose container 或 co-resident project
  驗證失敗：負載開始前拒絕執行。

## PASS 證據

Report 與總 gate 同時要求：

- 實際開始／完成時間證明至少 72 小時，不能只填 requested duration。
- 至少 95% 預期樣本；captured_at 嚴格遞增，單次 gap 不得超過 2.5 個採樣週期。
- 首樣本在開始後一個週期內，末樣本覆蓋 load completion 前最後一個週期。
- 每個樣本 health=200、env=staging、release identifiable、source commit 一致。
- 每個樣本都有 runtime metrics、Compose-scoped container stats 與 GPU stats。
- 零持續 memory leak、DB pool exhaustion 與 unrecoverable queue backlog。
- 八種 workload scenario 全部有流量且錯誤率在 Standard SLO 內。
- Locust 與 collector exit code 都為零，raw CSV／JSONL hash 完整。

Telemetry collector 本身可續寫是為了診斷；正式 soak 的 Locust 工作量不可無證據地
跨程序拼接，因此任何中斷後的續寫資料只能保留為診斷 artifact，不能通過 P5 gate。
