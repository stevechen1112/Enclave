# P5 Isolated Staging Campaign Runbook

本 runbook 是 P5 正式執行的唯一順序。Lite、Standard、Enterprise 使用同一 source
commit 與專用 tenant，但各自保留獨立 environment artifact；Standard artifact 再供
cost、degradation 與 soak 使用。任一步驟 FAIL／HOLD 都停止 campaign，不得跨版本拼接。

## 1. 固定 campaign 身分

建立全新且權限為 0700 的 artifact directory，記錄完整 Git commit、Compose project、
操作者與專用 tenant UUID。Fixture 必須是合成資料；所有密碼只由 secret manager 注入
環境變數。不得把 token pool、密碼或客戶資料提交 Git。

## 2. 先擷取三份 environment evidence

```bash
python scripts/capture_p5_environment.py \
  --base-url https://p5-staging.example.com \
  --compose-project enclave-p5 \
  --container web=enclave-p5-web-1 \
  --container worker=enclave-p5-worker-1 \
  --output artifacts/ops/p5/environment-standard.json \
  --confirm-isolated-staging
```

Lite 與 Enterprise 以同一命令在各自隔離環境再擷取一次。CPU 必須等於 profile 定義，
RAM／GPU 僅允許 10% 硬體標示誤差，disk 不得低於門檻；因此大機器不能替小 profile
產生容量宣稱。部署或重建任一 container 後，受影響環境的正式 run 必須從頭開始。

## 3. 建立專用負載帳號與 grounded fixture

依序執行 `provision_p5_load_users.py`、`prepare_p5_load_tokens.py` 與
`prepare_p5_grounded_fixture.py --activate-staging-fixture`。Lite、Standard、Enterprise
credential pool 至少分別提供 40、200、1,000 個不同帳號。Grounding evidence 必須
證明同一 tenant 的合成 SOP 可由 search 與 chat sources 找到。

## 4. 三種 2× capacity run

每個 profile 使用全新 output directory。以下為參數骨架；Lite、Standard、Enterprise
各執行一次，正式時間不得小於 900 秒：

```bash
python scripts/run_p5_capacity.py \
  --profile standard \
  --base-url https://p5-staging.example.com \
  --backend-base-url http://web:8000 \
  --output-dir artifacts/ops/p5/capacity-standard \
  --document-fixture artifacts/ops/p5/fixtures/document.pdf \
  --audio-fixture artifacts/ops/p5/fixtures/audio.wav \
  --video-fixture artifacts/ops/p5/fixtures/video.mp4 \
  --grounding-evidence artifacts/ops/p5/grounding.json \
  --environment-evidence artifacts/ops/p5/environment-standard.json \
  --credentials artifacts/ops/p5/standard-tokens.json \
  --backend-container enclave-p5-worker-1 \
  --metrics-container enclave-p5-web-1 \
  --compose-project enclave-p5 \
  --duration-seconds 900 \
  --telemetry-interval-seconds 60 \
  --confirm-isolated-staging
```

## 5. Cost guardrail drill

```bash
python scripts/run_p5_cost_guardrails.py \
  --base-url https://p5-staging.example.com \
  --tenant-id '<dedicated-tenant-uuid>' \
  --email '<dedicated-tenant-superuser-email>' \
  --environment-evidence artifacts/ops/p5/environment-standard.json \
  --compose-project enclave-p5 \
  --container enclave-p5-web-1 \
  --output artifacts/ops/p5/cost.report.json \
  --confirm-isolated-staging
```

Runner 必須證明登入者屬於同一 tenant、四種成本單位存在、cost-axis 429 生效，並在
`finally` 還原原 quota。輸出路徑必須全新。

## 6. 四種 degradation drill

依 [P5_DEGRADATION_DRILLS.md](P5_DEGRADATION_DRILLS.md) 產生 provenance-bound plans，
串行執行 provider slow、quota exhausted、queue saturated、sidecar unavailable。
每次都必須 recovery PASS 且三種安全計數為零。

## 7. Standard 72 小時 soak

只有前三份 capacity、cost 與四份 degradation report 都 PASS 才能開始。完整命令與
中斷處理見 [P5_SOAK.md](P5_SOAK.md)。Soak 必須引用 Standard environment artifact；若
runtime image 或 deployment 在 72 小時內改變，逐樣本 release／image binding 會使
campaign HOLD，必須重跑。

## 8. 組裝與獨立驗證

```bash
python scripts/assemble_p5_evidence.py \
  --capacity-report artifacts/ops/p5/capacity-lite/lite_capacity_report.json \
  --capacity-report artifacts/ops/p5/capacity-standard/standard_capacity_report.json \
  --capacity-report artifacts/ops/p5/capacity-enterprise/enterprise_capacity_report.json \
  --soak-report artifacts/ops/p5/soak/soak_report.json \
  --cost-report artifacts/ops/p5/cost.report.json \
  --degradation-report artifacts/ops/p5/degradation/provider_slow.report.json \
  --degradation-report artifacts/ops/p5/degradation/quota_exhausted.report.json \
  --degradation-report artifacts/ops/p5/degradation/queue_saturated.report.json \
  --degradation-report artifacts/ops/p5/degradation/sidecar_unavailable.report.json \
  --environment-evidence artifacts/ops/p5/environment-lite.json \
  --environment-evidence artifacts/ops/p5/environment-standard.json \
  --environment-evidence artifacts/ops/p5/environment-enterprise.json \
  --operator '<operator-id>' \
  --output artifacts/ops/p5/P5_CAPACITY_EVIDENCE.json \
  --confirm-isolated-staging

python scripts/verify_p5_capacity.py \
  --evidence artifacts/ops/p5/P5_CAPACITY_EVIDENCE.json
```

只有 verifier exit code 0 與 `status=PASS` 才能進入 P5 最終 Code Review。Code Review
仍須確認 raw artifact hashes、secret hygiene、production 未受影響與 campaign tenant
已清理或明確保留；Review PASS 後才能開放 P6。
