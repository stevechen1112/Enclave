# Input I9-2 資源隔離與孤兒工作復原 — Code Review

日期：2026-09-03

結果：PASS

## Review 結論

未發現阻擋進入 I9-3 的資料遺失、跨租戶 dispatch 或無界重試問題。

Review 過程特別修正兩項併發風險：

1. 自動復原原先若先 dispatch、再寫入 running，快速 Worker 可能已完成但被 reconciliation 覆寫回 running。現改為先提交 `recovery_dispatching`，再送 broker。
2. WorkerLost 若使用 `reject_on_worker_lost` 直接重新入列，OOM 可能形成不增加 attempt 的死亡循環。現由資料庫 stale reconciliation 執行有上限的復原與 dead-letter。

## 已確認行為

- Audio、video、長錄音進入 `input.media` queue。
- 文件、圖片 OCR 與 URL 解析進入 `input.document` queue。
- lifecycle、outbox、reconciliation 等工作留在 `celery` queue。
- Production 新增單一併發、2 GiB 上限的 `worker-input`；核心 Worker 不再同時承受 FFmpeg／OCR。
- FFmpeg 及常見數值函式庫限制處理執行緒，降低瞬間記憶體峰值。
- Input 工作具 soft／hard time limit，並以 late acknowledgement 配合資料庫復原。
- 每五分鐘掃描 stale ingestion；判定以最後活動時間而非單純開始時間。
- 可恢復工作同步更新 job、revision、asset 後重新 dispatch。
- 達最大嘗試次數時同步標記失敗並建立 dead-letter，不會永遠卡在處理中。
- 手動重試與自動復原共用同一個 canonical dispatcher。
- 維運跨租戶掃描仍要求 maintenance identity、RLS bypass audit，租戶內處理立即恢復 tenant context。

## 驗證證據

```text
focused unit / integration-safe suite: 69 passed
Python compileall: PASS
docker-compose.prod.yml YAML parse: PASS（16 services）
Celery route assertions: PASS
SQLite WorkerLost projection recovery: PASS
```

本機 PostgreSQL 測試服務當時未啟動，因此既有 `test_input_i7_operations_resilience.py` 的 PostgreSQL fixture 無法連線；相同 recovery 邏輯已由不依賴外部服務的 I9 SQLite 測試覆蓋，PostgreSQL、Compose 及實際 Worker 驗證列入 I9-6／I9-7 Gate。

## 剩餘風險

- 2 GiB 是首租戶目前主機的受控基線，不是商用容量承諾。
- 超大型或一小時影片仍需由 I9-6 真實媒體測試確認處理時間及峰值。
- UI 必須顯示自動復原狀態，避免 30 分鐘 stale window 被誤解為完成或失敗。
