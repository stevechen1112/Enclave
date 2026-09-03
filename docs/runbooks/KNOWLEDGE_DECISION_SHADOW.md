# Knowledge Decision Shadow Runbook

本 runbook 只允許 KQ3 `shadow`；不構成 KQ7 `enforce` 授權。

## 啟動前授權紀錄

Owner 必須明確提供並留存：

- tenant UUID 與允許的 subject／資料範圍；
- 模式固定為 `shadow`；
- 有效起訖時間；
- 綁定的 backend/frontend image、deployment manifest、KB revision、Knowledge Unit release 與 Pack versions；
- 允許保存的資料種類：pseudonymous tenant/request refs、hash、reason code、latency、重新授權後才可見的 source refs；
- retention class、legal hold owner、operator 與 rollback owner；
- 停止條件與 kill-switch 聯絡人。

缺任一欄位時保持 `KNOWLEDGE_DECISION_MODE=off`。

## 旗標

```text
KNOWLEDGE_DECISION_MODE=shadow
KNOWLEDGE_DECISION_TENANT_ALLOWLIST=<authorized tenant UUIDs>
KNOWLEDGE_DECISION_KILL_SWITCH=false
KNOWLEDGE_DECISION_SHADOW_STORE_PATH=<tenant DB 外的加密持久卷>
KNOWLEDGE_DECISION_SHADOW_KEY=<Fernet key from secret manager>
KNOWLEDGE_DECISION_SHADOW_RETENTION_DAYS=30
```

正式環境必須由 secret manager 提供獨立 Fernet key；不得把 key 寫入 repository、artifact 或一般 log。Store 是 local/in-process encrypted volume，不經網路；若改用 remote store，transport TLS 與 tenant-scoped service identity 為新 Gate。

## 首跑

1. 凍結並簽署 `artifacts/knowledge/KQ_SHADOW_THRESHOLD_MANIFEST_V1.json`，不得看過結果後覆寫。
2. 在 process-wide read-only barrier 下凍結 mutation sentinel。
3. 執行至少 30 個真實案例、至少 2 個 subject、至少 4 個 deny/forbidden 負例。
4. 排除 telemetry failure、execution failure、缺 release identity 或 duplicate request 的案例；不得把它們計入有效分母。
5. 分別計算 false acceptance、false rejection、transition matrix、execution failure、各 stage P50/P95/P99 與 sync/stream parity。
6. 再取 mutation sentinel；任何 row/digest delta 非 0 立即 kill switch。
7. 管理頁 `/system/decision-diffs` 只能由 owner/admin/auditor 讀取；每次讀 source refs 重新驗證 tenant、document status 與 tombstone。

## 關閉與回滾

先設 `KNOWLEDGE_DECISION_KILL_SWITCH=true` 或 `KNOWLEDGE_DECISION_MODE=off`。off 後不得再執行 shadow decision、writer 或 provider/model 呼叫。已存在的加密 artifacts 按 retention 到期清除；legal hold 阻止清除，解除後才可 purge。Purge 只留下 segment hash、筆數與時間，不保留本文。

Writer、store、管理頁或 metrics 故障不允許 fallback 到 tenant DB，也不得影響 legacy Ask 回答。
