# Phase P5 效能、容量、成本與穩定性 — 執行狀態與解鎖條件

日期：2026-08-28

Phase 狀態：`IN PROGRESS / ENVIRONMENT HOLD`

P6 entry：`CLOSED`

## 結論

P5 並未完成，因此不能宣稱產品化計畫 all done，也不能進入 P6。程式、測試工具、
證據模型與 fail-closed gate 可以持續開發；只有會干擾 production 或產生無效容量
結論的正式負載、故障注入與 72 小時 soak 被鎖住。

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
  co-resident Enclave project gate。
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
| P5 Code Review | 完整 evidence gate PASS 後進行 | BLOCKED BY EVIDENCE |

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

Environment HOLD 只凍結上述正式 live evidence，不凍結內部工程。等待專用主機期間，
仍應持續完成測試覆蓋、runbook、artifact schema、review findings 與部署自動化；
不得因外部環境尚未到位而停止整個產品化計畫，也不得跳過 P5 進 P6。
