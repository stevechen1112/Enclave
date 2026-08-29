# Input I8 第一租戶現場 Pilot Gate Code Review（2026-08-29）

結論：**ENGINEERING READY / FIELD PILOT NOT STARTED / GATE HOLD。** I8 工具、證據 ledger、租戶隔離、fail-closed gate 與管理介面已完成並通過內部 Code Review；尚無真實租戶 14–28 天資料與簽署驗收，因此不得宣稱第一租戶 Pilot、GA、SLA 或共享多租戶產品驗證完成。

## Review 身分

- 工作樹基線：`d85b1503e1058ec4865d3f21a4477a363205c351` 加本次未提交 Input I0–I8 工作樹。
- Schema revision：`input_i8_pilot_evidence_001`。
- Route file SHA-256：`bf73ae0335241a55e7194f799a1185b7faa60b4002262a6248262b588e583964`。
- Migration SHA-256：`258431b32677d67619ba51de70e6366e28e1d9ab258e6b4e9670051a3a1c6d21`。
- 未執行 production deployment。

## 完成範圍

- tenant-scoped Pilot、每日指標、incident、audit、retrospective 與 acceptance ledger。
- 專屬環境證據 hash、DPA ref、2–3 journey、metadata／術語／ACL／覆核責任人設定。
- 14–28 天連續資料、每 journey 每日覆蓋、success/retry/correction/p95/citation SLO。
- synthetic 永遠不能通過 field gate；未簽署 acceptance 永遠 HOLD。
- 最新 quality/security/permission audit 必須通過，pass audit 不接受零抽樣。
- incident 未解、復盤不完整、未設定 journey、無效 hash、試行前／未來證據與過早簽署全部 fail-closed。
- acceptance 寫入前先執行不含簽署本身的 preflight；證據不可覆寫。
- `/system/input-pilot` 清楚顯示 LIVE／synthetic、PASS／HOLD、觀察天數、稽核、incident 與 blockers。

## Code Review 發現與修正

1. **P0：I6–I8 新租戶表只有應用層 tenant filter，migration 未加 RLS。** 已在 I6、I7、I8 migration 補上 `tenant_isolation` policy，並在 production-like migration 驗證 `8/8 RLS enabled + FORCE RLS`。
2. **P1：任意 review owner UUID 可進入 journey。** 建立時改為驗證本租戶 active user。
3. **P1：future／pre-start metric、audit、incident 或 acceptance 可能污染不可變 ledger。** API 寫入前拒絕，gate 再次獨立驗證。
4. **P1：舊的 pass audit 可能遮蔽較新的 fail。** 改為每種 audit 僅採最新一次結果。
5. **P1：零抽樣 audit 可標記 pass。** API 與 gate 雙層拒絕。
6. **P1：acceptance 可在 SLO 證據完成前寫入。** accepted 決策寫入前必須通過 preflight，並驗證簽署時間不早於最後證據日。
7. **P1：缺少整體 Pilot retrospective。** 新增不可覆寫的 retrospective ref + SHA-256 與 gate 條件。
8. **P2：HOLD Pilot 可重新 start 並重設開始時間。** 啟動改為僅接受 ready 狀態，避免污染既有 ledger。
9. **P1：I7 telemetry 在舊 schema／精簡測試 schema 缺表時會中斷核心資產與影片交易。** metric insert 改用 nested savepoint 隔離並 fail-open 記錄警告；新增 storage failure 測試，確保 observability degradation 不回滾主交易。

修正後無已知 P0／P1 程式碼缺陷。

## 驗證結果

- I8 backend focused：8 passed。
- I6–I8、tenant boundary、ACL、upload、queue、capacity、DLQ related regression：最終 hardening 後 124 passed。
- 完整 backend regression：1,499 passed／12 skipped／0 failed；第一次全跑揭露的 5 個 telemetry schema compatibility failure 修正後全部通過。
- Frontend：35 files／120 tests passed。
- TypeScript `--noEmit`：PASS。
- ESLint：PASS。
- Vite production build：PASS；產物包含 `InputPilotPage` chunk。
- Ruff（I6–I8 migration、I8 model/service/API/tests）：PASS。
- Alembic：fresh upgrade → downgrade I7 → re-upgrade I8：PASS。
- PostgreSQL/pgvector 且 `RLS_ENFORCEMENT_ENABLED=true`：I6–I8 8 張新表均為 RLS enabled、FORCE RLS、1 個 tenant policy。
- `git diff --check`：PASS（僅既有 Windows LF/CRLF 提示）。

## 尚未完成的外部 gate

- 真實第一租戶、專屬環境、DPA 及文件存在性核驗。
- 2–3 條真實 journey 的 14–28 天連續使用證據。
- 真實裝置／網路／工廠資料、quality/security/permission audit。
- incident 與 near miss 復盤、客戶授權代表簽署。
- I7 live 2× capacity profiles、四種 degradation drill 與 72 小時 soak。
- acceptance 目前保存已簽文件 ref + SHA-256；系統不替代外部電子簽章或簽署權限驗證。

## Gate 決定

I8 **內部工程完成**，可交付給第一個受控 Pilot 使用；I8 **現場產品驗證仍為 HOLD**。不得把單元測試中的 logical live fixture 或本文件當成真實租戶驗收。正式狀態以 `artifacts/input/i8_pilot_status.json` 與實際 Pilot gate API 為準。

## Post-review hardening

證據操作 UI、tenant-scoped evidence view、時區處理與 acceptance preflight UX 已於後續 review 補齊；權威補充文件為 `PHASE_INPUT_I8_PREPILOT_HARDENING_CODE_REVIEW_2026-08-29.md`。
