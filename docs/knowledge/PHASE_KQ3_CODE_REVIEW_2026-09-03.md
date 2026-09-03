# Phase KQ3 Code Review — 2026-09-03

結論：`BLOCKED`
Gate：`KQ-SHADOW-01`
範圍：Live Ask shadow code、out-of-band telemetry、授權唯讀 UI；未部署

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

## 未解除 Gate

- 尚無 tenant Owner 的獨立 Shadow 核准（tenant、scope、期限、release、資料使用、operator、rollback owner）。
- 尚未部署最終候選 image，因此沒有 30 個正式真實案例、2 subjects、4 deny/forbidden、mutation=0 與 sync/stream parity 的首跑證據。
- 此缺口不能用 local synthetic tests 或 KQ0 baseline 取代。

## 驗證

- KQ3 專用：10 passed。
- KQ1–KQ3、QueryPlan、Knowledge engine、production shadow contract：83 passed。
- TypeScript `tsc -b`：PASS；Vite production build：PASS。
- `compileall`、`git diff --check`：PASS。

## Review 決定

`BLOCKED`

依 phase gate 與 tenant authorization 規則，未取得明確 Shadow 授權前不得部署、不得執行正式首跑、不得開始 KQ4。
