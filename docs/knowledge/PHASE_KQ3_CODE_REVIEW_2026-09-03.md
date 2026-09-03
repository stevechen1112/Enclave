# Phase KQ3 Code Review — 2026-09-03

結論：`PASS TO NEXT PHASE`
Gate：`KQ-SHADOW-01`
範圍：Live Ask shadow code、out-of-band telemetry、授權唯讀 UI、正式唯讀 Shadow 首跑與完整重跑

## 程式結果

KQ3 code complete：新增預設 off 的 mode/allowlist/kill switch，sync 與 stream 由同一 `retrieve_context` adapter 執行；enforce 在 KQ7 Owner approval service 完成前強制退回 off。Telemetry 只寫 tenant operational DB 外的 Fernet-encrypted append-only JSONL segment，支援 superseding record、retention、legal hold、content-free purge audit、tenant/role/source 重新授權與 writer failure isolation。

`/knowledge/decision-diffs` 與 `/system/decision-diffs` 提供管理端唯讀檢視。Threshold manifest 已在正式首跑前凍結，false accept/reject、transition、execution failure 與 stage latency 各自計算。

## Review checklist

1. Canonical owner：Live path shadow 只呼叫 KQ2 EvidenceOrchestrator；legacy 回答完全不變。
2. 平行 aggregate/retrieval/revision/citation：無。
3. ACL/RLS/revision/deny：來源顯示重新查 tenant、completed 與 tombstone；decision admission 沿用 KQ2。
4. Sync/stream：兩路共用 `retrieve_context`，channel 明確標記。
5. Provider failure：獨立 execution status，排除有效量測分母。
6. False acceptance/rejection：分欄、分率、分母明確。
7. Migration：無 tenant DB migration。
8. Pack failure：獨立 execution status，不轉 absent。
9. Privacy：Fernet at-rest encryption；沒有 tenant content、prompt、token 或 password 明文。
10. Regression：83 passed；TypeScript 與 Vite build PASS。
11. Rollback：mode off 或 kill switch；不重建 index、不改 legacy answer。
12. Evidence binding：threshold 要求 formal run 綁 exact final release；尚未執行。
13. Shadow store：tenant DB 外、append-only、加密、retention/legal hold/purge audit、授權唯讀，writer 不 fallback。
14. Enforce：硬性 off，沒有推定 Owner 授權。

## 正式 Shadow 證據

- Owner 授權已綁定合成 Demo tenant、scope、兩小時時窗、資料種類、30 天 retention、operator、rollback owner、release、image、case/threshold/runner hashes；公開 Web path 在正式 runner 期間及完成後均維持 `off`。
- 最終正式 release：`kq3-shadow-d223425`；source `d223425b7c949f70bf73a01ea7dcc9b5ef9c9463`；deployment manifest `dm-1b985d37db8da00104263c20`；backend image `sha256:33b0044b8045075d575f9043501d31cb4cad21913ca593341a57fe616d44bde8`；frontend image `sha256:6e0ed172641f0c5964496689faa6f166e332f7c3c6dcd6f5f4cde5b0bdfba485`。
- 30 個凍結案例、2 個既有 subject、4 個跨租戶 forbidden 文件負例；每案各跑 baseline、sync Shadow 與 stream Shadow。30/30 有效，新增 60 筆加密 append-only telemetry。
- tenant mutation `0`；legacy context digest 30/30 不變；expected documents 30/30；forbidden absence 30/30；sync/stream parity `1.0`；execution failure `0.0`。
- ground-truth adjudicated false acceptance `0.0`、false rejection `0.0`；transition candidates 另列為 `abstain→complete` 6、`answer→complete` 24，未把候選直接冒充錯誤率。
- decision overhead P50/P95/P99 為 `0.11885 / 0.15469 / 0.3289 ms`，均低於預凍結 `20 / 75 / 150 ms`。
- 首次執行如實留下 FAIL artifact：它揭露 transition candidate labels 顛倒，以及 runner 把候選當 final rate。門檻與 30 題完全未改；修正語意後以新 release 完整重跑。FAIL SHA-256 `30bae59126bf2e2705e2224de56b872b369eae17a4b91cb100a5563528cd748d`，PASS SHA-256 `f3cc0b4d5e7784bd17e2b85a54aafd7177ed8678a5837b70a87c42a6b856462c`。
- 加密 store 共保留原首跑與完整重跑 120 筆；明文掃描未出現題目、文件名、password 或 token。正式環境仍為 `KNOWLEDGE_DECISION_MODE=off`，rollback point 為 `input-i9-dd5a6bd`。

## 驗證

- KQ3／KQ2／production Shadow focused suite：25 passed。
- KQ1–KQ3、QueryPlan、Knowledge engine、production shadow contract：83 passed。
- TypeScript `tsc -b`：PASS；Vite production build：PASS。
- `compileall`、`git diff --check`：PASS。

## Review 決定

`PASS TO NEXT PHASE`

KQ-SHADOW-01 已依預凍結門檻通過，可開始 KQ4。此 PASS 不構成 KQ7 Enforce 授權；正式路徑保持 `off`。
