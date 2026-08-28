# Phase P5 效能、容量、成本與穩定性 — 執行狀態與解鎖條件

日期：2026-08-28

Phase 狀態：`ENGINEERING COMPLETE / LIVE VALIDATION WAIVED`

P6 entry：`OPEN BY PRODUCT RISK ACCEPTANCE`

## 結論

P5 工程、測試工具、證據模型與 fail-closed gate 已完成。正式負載、故障注入與
72 小時 soak 因會干擾 production 或產生無效容量結論而未執行；產品負責人於
2026-08-28 接受此風險並要求直接進入 P6。未執行項目維持 `WAIVED / NOT RUN`，
不得宣稱為 PASS。決策見 `decisions/P5_LIVE_VALIDATION_WAIVER_2026-08-28.md`。

2026-08-28 對 staging `8c4065f2a9d94e80262ba0f9fcc5ed961bbf04de`
的實測結果如下：

- `/health`：PASS，環境為 staging，release identity 完整且 source dirty=false。
- Environment capture：HOLD。
- 實測硬體：4 CPU、8.327 GB RAM、168.482 GB disk、0 GB GPU VRAM。
- 同一 Docker host 偵測到另一個 Enclave Compose project：`enclave`（production）。
- `isolated_staging=false`；正式 runner 會在開始負載前 fail-fast。
- production `/opt/enclave` 未被變更，也未執行正式高負載或故障注入。

## 已完成的內部工程

- Lite／Standard／Enterprise 唯一權威容量規格與硬體門檻。
- Evidence schema v2 支援三份 profile-sized environment；CPU 必須等於 profile，
  RAM／GPU 僅允許 10% 標示誤差，禁止以 Enterprise 主機冒充 Lite／Standard 證據。
- 登入、資產、搜尋、有來源問答、文件、批次 ingestion、音訊與影片 queue 的
  Locust workload contract。
- 15 分鐘 2× capacity runner 與不可縮短的 Standard 72 小時 soak runner。
- Standard soak 已強制 fresh artifacts、100 個唯一同租戶 token、metrics container
  Compose 綁定、Locust／collector 互相 fail-fast，以及逐樣本 release／時間連續性／
  health／metrics／container／GPU 完整性；只完成內部 contract test，尚未執行 72 小時。
- 專案範圍 Docker telemetry、內網 metrics、DB pool、Redis、Celery backlog、
  object I/O、CPU、RAM、GPU、provider latency/error 採樣與樣本完整性驗證。
- Grounded SOP fixture、search/chat source contract，以及 post-load tenant isolation
  和 ingestion job reconciliation。
- 每租戶 storage／audio／video／query 成本報表與 live quota fail-closed 驗證。
- Environment evidence 實測、runtime image ID、source commit、artifact hash 與
  co-resident Enclave project gate；container ID 也逐樣本比對，重建同版 container
  仍會使正式 evidence FAIL。
- Degradation evidence 綁定 commit／Compose／tenant／environment；只接受同 commit
  且雜湊相符的版本控制 driver 與 integrity probe，禁止敏感資訊進 argv，並要求
  recovery、data loss、false completion 與 cross-tenant leak 的實際觀測。四種
  live driver、plan generator 與中斷復原流程已完成內部實作，但在專用主機執行前
  仍維持 NOT RUN，不得把單元測試視為 live evidence。

## 尚未完成、不可偽造的正式證據

| 項目 | 需要的正式結果 | 目前狀態 |
|---|---|---|
| Lite capacity | 4C／8GB 以上獨立環境，40 users、480 RPM、15 分鐘、至少 15 個樣本 | NOT RUN |
| Standard capacity | 8C／32GB／8GB VRAM 以上獨立環境，200 users、2,400 RPM、15 分鐘 | NOT RUN |
| Enterprise capacity | 16C／64GB／24GB VRAM 以上獨立環境，1,000 users、12,000 RPM、15 分鐘 | NOT RUN |
| Degradation | provider slow、quota exhausted、queue saturated、sidecar unavailable 各一份 live PASS | NOT RUN |
| Soak | Standard 1× peak、259,200 秒、五分鐘內採樣、樣本完整率至少 95% | NOT RUN |
| P5 商用規模最終簽核 | 完整 evidence gate PASS 後進行 | WAIVED / NOT RUN |

先前在共用主機上開始的試跑只用於發現 runner 與 telemetry 問題，已停止並保留為
診斷 artifact；不得改標為 capacity PASS。

## 解鎖環境

最安全的作法是提供一台可重建、只承載 `enclave-p5` Compose project 的專用主機，
依序套用三種資源 profile；或提供三台分別符合 profile 的專用主機。無論哪一種，
都必須滿足：

1. 不存在 production 或其他 Enclave Compose project。
2. 使用專用 staging tenant、專用 credential pool 與合成 fixture。
3. release source commit、runtime image ID 與 environment evidence 完整一致。
4. Standard／Enterprise 的 GPU 門檻不能以 Lite 主機或未量測值代替。
5. 壓測期間保留完整 Locust、telemetry、integrity、grounding 與環境 artifact。

## 解鎖後執行順序

1. 部署同一個待驗 release，capture environment evidence 並確認 PASS。
2. 依序執行 Lite、Standard、Enterprise 15 分鐘 2× capacity run。
3. 執行四種 live degradation drill，逐次確認 recovery 與資料完整性。
4. 通過短測後執行 Standard 72 小時 soak。
5. 組裝 P5 evidence，執行獨立 verifier。
6. Evidence PASS 後進行完整 Code Review；只有 Review PASS 才能進 P6。

## 持續推進原則

正式 live evidence 仍等待專用主機；P6 依產品風險接受決策開放。此狀態不得被
解讀為三種 deployment profile、故障演練或 72 小時穩定性已通過。
