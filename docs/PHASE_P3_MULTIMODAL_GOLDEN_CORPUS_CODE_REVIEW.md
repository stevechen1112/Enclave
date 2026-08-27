# Phase P3 — 多模態 Golden Corpus 與品質閘門 Code Review

**Review date:** 2026-08-28
**Implementation commit:** `7633d423643bdcd4cc4d5e8e944ee2765d82d0de`
**Staging release:** `staging-7633d42`
**Internal implementation gate:** PASS
**Code review:** PASS（Critical／High 未處理 finding：0）
**Staging internal replay gate:** PASS
**Phase gate:** PASS
**P4 entry:** ALLOWED

## Conclusion

P3 的 repository-safe synthetic golden corpus、ground truth schema、provider matrix、degraded-mode contract、per-slice evaluator 與 exact-release staging replay 已完成。15 個案例涵蓋原生與掃描文件、表格、圖片、四種音訊及四種影片情境；同一份 sealed corpus 在 mock contract、degraded 與 internal replay 三種模式都通過。

最終 staging replay 的 terminal-state rate、evidence locator precision 與 recall 都是 100%；hallucination、錯誤版本引用、低信心未送審、高風險未拒答、SOP conflict 漏攔截與跨租戶 evidence 均為 0。完整 backend regression、frontend unit/build、映像身分、服務健康與 runtime log review 也通過，因此 P3 phase gate 為 PASS，可進入 P4。

這個結論證明內部 regression floor 與管線契約已成立，不代表真實客戶資料、不同產業、各種口音／噪音／攝影條件或第三方 provider 的商業 GA 泛化品質已獲證明。

## Implemented

- 建立 15-case 多模態 manifest 與可重建 fixtures，涵蓋 PDF、DOCX、XLSX、CSV、圖片、音訊與影片。
- ground truth 可描述文字、表格座標、OCR 區域、speaker／時間碼、步驟、條件、風險、例外、SOP conflict 與 evidence locator。
- evaluator 分別輸出 terminal state、locator precision／recall、critical errors 與每個 slice 結果，不用總平均掩蓋弱項。
- provider matrix 強制區分 `mock_contract`、`degraded` 與 `internal_replay`，並驗證 sealed corpus hash 與 provenance。
- 文件／表格／圖片 ingestion 統一投影為 canonical `DerivedArtifact` 與 `EvidenceSpan`；PDF page、DOCX section、XLSX cell、CSV row 與 image bbox 都保留來源座標。
- 音訊與影片 evidence 保留 speaker、時間碼與來源 lineage；leading silence、影片 duration 邊界及關鍵幀 seek 都有回歸保護。
- 低品質文件／低 OCR 信心會進入 review；無聲影片進入可解釋的 `completed_no_knowledge` terminal state。
- 高風險影片、SOP conflict、低信心、錯誤版本與跨租戶 evidence 都是 gate-blocking invariant。

## Review findings fixed before PASS

1. **文件、表格與圖片原本沒有完整投影為 canonical EvidenceSpan。** 已補上原生 parse 座標與 artifact projection，使 retrieval evidence 能回指 page、section、cell、row 或 bbox。
2. **`file_type=image` 曾被映射成一般文件類型。** 已改用語意 asset kind，並加入 image slice regression。
3. **低 OCR 信心仍可能進入 ready。** 品質政策現會把低分或低 OCR confidence 資產送入 review。
4. **CSV lineage 曾繼承暫存 UUID 檔名。** fallback 現使用原始 document filename，避免 evidence 指向暫存處理名稱。
5. **FFmpeg 在影片尾端擷取關鍵幀可能發生 endpoint seek error。** 已保留 duration margin 並以 fixture 覆蓋。
6. **部分 ASR provider 會壓縮開頭靜音，造成 evidence 時間碼向前漂移。** 現以 audio activity 偵測做有界 forward alignment，並限制在影片 duration 內。
7. **初版 replay 以資產全部 EvidenceSpan 比對單一 query ground truth。** 已改為選擇 query-relevant knowledge artifact，避免把正確但不相關的其他 evidence 誤判為 false positive。
8. **無聲影片的 DB ready 狀態與評估語意不一致。** replay 現明確投影為 `completed_no_knowledge`，保留可解釋性且不製造假知識。
9. **手持影片 ground truth 的結束時間與實際可重建 audio activity 不一致。** 已修正 sealed fixture ground truth，最終 exact-commit replay 重跑通過。

## Verification evidence

| 驗證 | 結果 |
|---|---|
| Sealed corpus | 15 cases；corpus SHA-256 `e62d04c274028a984354c71d18883ace56e7f5da1ac13145f29d04abc9952092` |
| Provider matrix | PASS；`mock_contract`、`degraded`、`internal_replay` 無缺漏或失敗模式 |
| Exact-release internal replay | PASS；15／15 terminal；release `staging-7633d42` |
| Terminal-state rate | 100%（gate ≥ 98%） |
| Evidence locator precision | 100%（gate ≥ 95%） |
| Evidence locator recall | 100%（gate ≥ 95%） |
| Critical error matrix | 0；六種 critical errors 全部為 0 |
| Per-slice results | 15／15 slices PASS；每個 slice 獨立列出 |
| Full backend regression | 1,289 passed，12 skipped，0 failed |
| Frontend unit／build | 25 files／88 passed；Vite production build PASS（3,342 modules） |
| Static quality checks | Ruff、Black check、diff check PASS |
| Staging runtime | web、worker、frontend、gateway 與相依服務 healthy；replay window 無 ERROR／CRITICAL／Traceback |
| Release identity | source commit `7633d423643bdcd4cc4d5e8e944ee2765d82d0de`；dirty `false`；schema `p2_tenant_hard_isolation_001` |

本機完整 pytest 的 12 個 skip 是需要專用外部環境或 live provider 的明確測試；P3 所需的 exact-release internal replay 已在獨立 staging 執行，不能由 mock-only 結果替代。Degraded mode 的 locator 指標標為 not applicable，gate 驗證的是 provider 缺失時能進入正確 terminal／review 狀態，且不得幻覺或假完成。

## Residual risks and boundary

- corpus 是可重建的內部 synthetic contract corpus；15 cases、每個 slice 一個案例，是 regression floor，不是跨客戶或跨產業的統計代表樣本。
- OCR、ASR、embedding、prompt、model、parser、chunking 與 retrieval provider 都可能漂移；任何相關變更仍必須重跑 sealed regression 與 exact-release replay。
- 圖片 OCR evidence 目前能追到來源圖片，但整圖 fallback bbox 為 `[0, 0, 1, 1]`；可追溯性成立，尚未證明 word-level region precision。
- 尚未完成真機弱網、極端噪音、長時間連續錄影、更多語言／口音與客戶私有格式的外部 holdout。
- P3 不包含 P4 的 backup／restore、故障注入、alert fire／recover 與營運閉環，也不包含 production deployment 授權。
- Production `/opt/enclave` 未因本次 P3 驗證而變更；所有 live replay 都在 `/opt/enclave-staging` 執行。

## Gate decision

- **Internal implementation：PASS**
- **Code review：PASS**
- **Critical／High unhandled findings：0**
- **Staging internal replay：PASS**
- **Phase P3：PASS**
- **P4 entry：ALLOWED**
