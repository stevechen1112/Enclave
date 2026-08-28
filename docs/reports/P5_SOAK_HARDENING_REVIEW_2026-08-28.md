# P5 Soak Runner Hardening — Internal Code Review

日期：2026-08-28

狀態：程式 Review PASS；正式 72 小時 live evidence NOT RUN。

## 已關閉 findings

| Finding | 處置 |
|---|---|
| Locust 提前失敗仍等待 collector 接近 72 小時 | 兩程序改為互相監控，任一提前死亡立即停止另一方 |
| Collector recovery wait 又使用完整 72 小時 timeout | timeout 改為 recovery＋sample interval＋180 秒 |
| terminate 失敗可能留下孤兒程序 | 統一 terminate→bounded wait→kill→bounded wait |
| 可把舊 telemetry 接到新 Locust run | 正式 runner 強制 fresh formal artifact paths |
| 只看 sample count，未證明時間覆蓋 | 驗證 timezone、單調性、首尾覆蓋與 max gap |
| Telemetry 可混入另一 release | 每個 sample 都比對 staging、identifiable 與 source commit |
| Metrics container 可誤指 production | Docker inspect 驗證 running Compose project／service／image identity |
| Token pool 只驗第一個 token | Standard 開跑前驗證 100 個唯一 token 全部同租戶 |
| Soak 可改用 Lite／Enterprise | runner 與總 gate 都固定 Standard |
| 非 JSON 或 JSON array 可被忽略 | 非 object line 計為 telemetry integrity failure |
| Capacity runner 可指向未確認環境 | 正式執行強制 `--confirm-isolated-staging` |
| Capacity runner 可混入舊輸出 | 同 profile 的 CSV／telemetry／integrity／report／log 必須全新 |
| Capacity telemetry 只看彙總值 | 與 soak 共用逐樣本時間、staging release、commit、metrics 與 container 完整性驗證 |
| Capacity 公開 URL／integrity container 可指向錯誤 release | 開跑前驗證 staging `/health` commit，並把 metrics 與 backend container 都綁定同一 Compose project |
| 可放寬採樣間隔但仍宣稱樣本充分 | 15 分鐘正式 run 的間隔上限由 900 秒／15 樣本推導為 60 秒，runner、report、gate 三層拒絕超限 |

## 驗證

- Valid synthetic 72 小時、864 樣本、1,200 RPM evidence：PASS。
- Short duration、release mismatch、invalid JSON、non-object JSON、excessive gap：FAIL。
- Metrics container production-project mismatch：FAIL。
- Process terminate timeout：會升級為 kill。
- 正式 shared staging 未執行 72 小時負載；production 未變更。

本 review 不開放 P6。只有獨立主機完成 live soak、P5 evidence verifier PASS 與最終
Phase P5 Code Review PASS 後才能進入下一階段。
