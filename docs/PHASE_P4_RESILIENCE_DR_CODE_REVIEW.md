# Phase P4 — 故障注入、備份還原與營運閉環 Code Review

**Review date:** 2026-08-28
**Application implementation commit:** `916873350f8fb812635c0a80253b71fb7c9a2e5d`
**Operations restore commit:** `300893530ee32989632c76a5b97d9e360952e46f`
**Evidence gate commit:** `f09076341153ca32b8c29a0db322b7ad43862fcb`
**Staging release:** `staging-9168733`
**Evidence:** `docs/reports/P4_RESILIENCE_EVIDENCE_2026-08-28.json`
**Internal implementation gate:** PASS
**Code review:** PASS（Critical／High 未處理 finding：0）
**Phase gate:** PASS
**P5 entry:** ALLOWED

## Conclusion

P4 已完成隔離 backup／restore、N-1 application rollback、10 類故障注入、retry／dead-letter、5 條 alert fire／recover、runtime readiness 與機器化 evidence gate。最終 application staging release 是 `staging-9168733`，source dirty 為 `false`；7 個必要場景在該 release live 執行，ASR、OCR 與 ClamAV 以 fail-closed contract 執行。

最新 restore drill 將 PostgreSQL dump 還原到全新、無對外網路的 disposable container，並把 object 與 configuration archives 真正解包到 fresh isolation roots 後逐檔比對。結果為 103 tables、168／168 objects、18／18 configuration files，bytes 全部相符；RTO 5 秒、RPO 0，低於內部 900／300 秒目標。N-1 application rollback 另以完整服務執行 asset read、review、sealed retrieval 與 tenant isolation smoke，跨租戶資產讀取為 404，沒有刪除 durable objects。

P4 證明的是內部 staging 的故障安全與可恢復基線，不等於 production DR 演練、外部告警送達、客戶資料規模或 72 小時穩定性已獲證明。Production `/opt/enclave` 未被本 phase 修改。

## Implemented

- 新增 fail-closed P4 evidence schema、validator、空白範本與 CI gate；缺 fault、alert、digest、RTO／RPO、source mutation、restored inventory 或 operator attestation 都會 HOLD。
- 新增 fresh isolated PostgreSQL restore drill；DB dump、object archive、index inventory 與 configuration archive 都保留 SHA-256，raw backup 為 owner-only 且不進版控。
- object／configuration archives 只允許 regular file／directory，拒絕 path traversal、credential path、symlink、hardlink 與 device，並在 fresh root 真正 materialize 後比對 objects／files／bytes。
- 修正正式 DR 腳本，使其消費實際 backup 檔名與 canonical upload volume；缺 DB 或 upload archive、archive 越界或含 link 時，在停服務前 fail closed。
- `/health` 使用專用 NullPool、2 秒 connect／statement timeout 的 DB readiness engine；DB unavailable 回 sanitized 503，恢復後回 200。
- `/metrics` 在同一 Uvicorn worker 即時刷新 DB dependency gauge，避免多 worker process 各自持有 stale metric。
- 新增 `DatabaseUnavailable` 告警；HighErrorRate、HighLatency、ServiceDown、DatabaseUnavailable、HighConcurrency 都有 Prometheus fire／recover 規則測試。
- upload spool 或 object backend 不可用時回可操作 503，明確表示資料未發布；已建立的孤兒 document row 會 tombstone。
- Redis 故障會在 operator health 顯示 dependency unavailable 與 overall degraded，恢復後回 healthy。
- outbox 的 retry budget、idempotent claim 與 exhausted→dead-letter tenant lineage 都有持久化測試。

## Review findings fixed before PASS

1. **Restore drill 初版查詢不存在的 `document_chunks`，無法還原實際 legacy canonical index。** 已改查真實 `documentchunks`，並加入 regression。
2. **正式 DR 腳本使用的 DB／upload backup 名稱與產出不一致，且原本還原 host path 而非 canonical named volume。** 已對齊 `.sql`／`.tgz` 產物、`init-storage` volume、gateway 與 worker-beat。
3. **Object backend 故障最初會成為 generic 500 並留下已 commit 的孤兒列。** 已改成 safe 503、tombstone 與明確 operator message。
4. **Local upload spool 在 backend `put()` 前故障時仍是 generic 500。** `mkdir`／write 的 `OSError` 現在同樣 fail closed，且不建立 document row。
5. **Root health 原本不檢查 DB，資料庫停機時可能保持假健康；初版 gauge 也可能因 2 個 Uvicorn workers 讀到 stale state。** 已新增 fast readiness engine、503、同 worker scrape refresh 與 live 0→1 驗證。
6. **Redis dependency 雖顯示 unavailable，overall health 曾仍顯示 healthy。** 現在任何 DB／Redis required dependency 異常都顯示 degraded。
7. **Restore drill 初版只建立 object／configuration archive 並安全掃描，沒有真的解包，卻標示 restore PASS。** Code review 將此列為 High；現已在 fresh isolation roots materialize 並驗證 count／bytes，gate 也強制要求 restored inventory 相等。
8. **正式 DR 在缺必要 archive 時會先停服務再跳過，可能留下半恢復狀態。** 現在所有 durable component preflight 都在 stop 之前，缺件直接拒絕操作。
9. **Evidence gate 曾只相信 `restore_status=PASS` 字串，未強制 source 不變、secret exclusion 與 restored inventory。** 現已 fail closed 檢查所有欄位，並加入負向測試。
10. **Retry budget／dead-letter 有實作但沒有直接持久化驗收。** 已補 budget 未耗盡維持 retryable，以及第 5 次失敗寫入同租戶 DLQ 的測試。

## Verification evidence

| 驗證 | 結果 |
|---|---|
| Machine evidence gate | PASS；errors `[]` |
| Fresh isolated DB restore | PASS；103 tables；SHA-256 `812c601f...966d56` |
| Object restore | PASS；168 backup／168 restored；8,589,608 bytes 一致 |
| Configuration restore | PASS；18 backup／18 restored；55,189 bytes 一致；secret material `false` |
| Index restore | PASS；inventory `83|83|10830`；source／restored 一致 |
| RTO／RPO | 5 秒／0 秒；targets 900 秒／300 秒 |
| N-1 application rollback | PASS；約 41 秒；asset、review、sealed retrieval、tenant isolation 全過 |
| Live fault injection | 7／7 PASS：Redis、worker、embedding、object store、DB、network timeout、duplicate delivery |
| Contract fault injection | 3／3 PASS：ASR、OCR、ClamAV；fail closed／degraded，無假完成 |
| Worker recovery | document `uploading`→`completed` |
| Embedding／network recovery | document `embedding`→`completed` |
| Object storage recovery | outage 503＋「資料未發布」；recovery upload 200 |
| Database recovery | health 503→200；gauge 0→1；documents 84→84 |
| Duplicate delivery | 兩次皆 `review_required` 且 `idempotent=true` |
| Alert lifecycle | 5／5 fire＋recover；promtool PASS |
| Fault／provider／outbox contracts | 122 tests PASS；另有 retry／DLQ targeted tests PASS |
| Full backend regression | 1,314 passed，12 skipped，0 failed |
| Frontend unit／build | 25 files／88 passed；Vite production build PASS（3,342 modules） |
| Release identity | `staging-9168733`；source `9168733...`；dirty `false`；schema `p2_tenant_hard_isolation_001` |
| Runtime after drills | web、worker、frontend、gateway、DB、Redis、embedding service healthy／running |

完整機器可讀資料、IDs、digests、image digests 與每個 fault invariant 保存在 `docs/reports/P4_RESILIENCE_EVIDENCE_2026-08-28.json`。

## Residual risks and boundary

- Restore 使用內部 staging 的 1 MB 級 DB、168 個 objects 與 83 個 embedding rows；大資料量、慢磁碟與跨區復原屬 P5／正式 DR 演練範圍。
- RPO 0 是 on-demand snapshot 相對於 drill start 的量測，不代表 production continuous-backup lag 已達 0。
- ASR、OCR 與 ClamAV 此次是 contract fail-closed；尚未中斷真實付費／外部 provider 帳號或網路。
- Object-store live fault 注入 canonical local volume 權限；尚未涵蓋真實 S3-compatible control plane、DNS、partial multipart 或 regional outage。
- N-1 drill 保持目前 forward-compatible DB schema，只切換 application images；沒有對 production 執行 destructive schema downgrade。
- Alert fire／recover 由 promtool 驗證，尚未證明外部 Alertmanager、Email／Slack／Pager 通知送達與值班人員確認。
- Full service rollback smoke 與 fresh data-component restore 是同一 P4 campaign 的兩個隔離步驟；blank-host 全套 DNS、TLS、provider credentials 與 object service 重建仍需正式 runbook 演練。
- P4 不涵蓋容量模型、兩倍尖峰 load、成本 guardrail 或 72 小時 soak；這些是 P5 gate。
- Production `/opt/enclave` 未變更；本次 live drills 全部在 `/opt/enclave-staging`。

## Gate decision

- **Internal implementation：PASS**
- **Code review：PASS**
- **Critical／High unhandled findings：0**
- **Fault／restore／rollback／alert evidence：PASS**
- **Phase P4：PASS**
- **P5 entry：ALLOWED**
