# Input I0 Telemetry Baseline — 2026-08-28

狀態：`CODE/EVIDENCE INVENTORY COMPLETE / LIVE INPUT SLO NOT MEASURED`

## 基準身分

- Production release：`production-dc3c9ef57d237`
- Source commit：`dc3c9ef57d23787479073389253596c88edb5572`
- Baseline 類型：既有程式、正式驗證文件與 P5 waiver 對帳
- 本報告沒有執行新的 production load、soak、弱網、實體裝置或 provider 壓測。

## 已有 telemetry primitives

| 範圍 | 指標／證據 | I0 判定 |
|---|---|---|
| HTTP | `http_requests_total`、`http_request_duration_seconds`、`http_requests_in_progress` | 可依正規化 route 觀察 request/error/latency |
| Dependency | `enclave_dependency_ready` | 可記錄必要 dependency readiness，但不是 Input capability health probe |
| DB | pool size、checked-out、exhaustion | P5 collector 可彙整；尚無 Input live campaign |
| Queue | `enclave_celery_queue_depth` | 有全域 backlog gauge；尚無 tenant／asset-kind queue wait |
| Storage | `enclave_object_io_duration_seconds` | 有 backend/operation/ok latency；尚無 upload session／bytes／resume 指標 |
| Provider | `enclave_provider_duration_seconds` | 有 provider/ok latency；尚無 capability、asset kind、quality/degradation 維度 |
| Quota | `enclave_quota_exceeded_total` | 可依 axis 計數；尚無 Input journey funnel |
| STT | `enclave_mka_stt_duration_seconds` | 綁在 MKA，不能作為平台 Input 音訊 SLO 權威 |
| P5 tooling | capacity、degradation、telemetry、soak verifier | 工程測試已完成；live campaign `WAIVED / NOT RUN` |

## 尚無 production evidence 的 Input 指標

以下全部記為 `NOT_MEASURED`，不得以單元測試或 synthetic browser test 代替：

- intake acknowledgement p50/p95/p99；
- upload throughput、bytes accepted、checksum failure、retry 與 duplicate rate；
- resumable session recovery（目前通用續傳尚未實作）；
- queue wait 與 processing duration，依 tenant／asset kind／adapter／provider 分解；
- accepted → processing → review/ready/partial/failed funnel；
- OCR／ASR／video 的品質與人工覆核率；
- 行動裝置 capture-to-accepted 成功率；
- 工廠弱網、斷線、登入逾時與長檔復原率；
- tenant fairness、兩倍尖峰、degradation 與 72 小時 soak。

## I0 結論

現有觀測底座足以支撐後續 instrumentation，但尚不足以證明 Input 的可靠性、速度或商用容量。Input I1–I6 新增的 journey 與狀態必須帶入低基數 metrics；Input I7 必須執行不可用單元測試取代的 live campaign，才能把本報告中的 `NOT_MEASURED` 改成實測值。
