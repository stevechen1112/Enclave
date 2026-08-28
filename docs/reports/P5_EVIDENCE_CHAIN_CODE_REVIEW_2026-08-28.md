# P5 Evidence Chain Code Review — 2026-08-28

狀態：`INTERNAL IMPLEMENTATION REVIEW PASS / LIVE CAMPAIGN NOT RUN`

本 review 涵蓋 capacity、cost、degradation、telemetry、soak、environment capture、
evidence assembly 與 verifier。未發現尚未處理的 Critical／High 程式 finding；本結論
不等於商用規模 live evidence PASS。P6 後續由產品負責人的風險接受決策開放，
不是由此 review 自動開放。

## 已關閉 findings

| Finding | 修正 |
|---|---|
| 單一 environment 可讓大機器冒充小 profile | Evidence schema 升至 v2；三份 capacity report 各自綁定 profile-sized environment，CPU 必須相等、RAM／GPU 上限誤差 10% |
| Report 只綁 image tag／commit | Environment、runner 與 telemetry 同時綁 container ID 與 immutable image ID |
| 72 小時內重建同 commit container 不易察覺 | 每個 telemetry sample 都重新 inspect Compose containers；instance 或 image 漂移立即 FAIL |
| Cost drill 可測到另一租戶或環境 | 驗證登入者 tenant、staging health、source commit、Compose、environment hash 與 Web instance |
| Degradation plan 可手改 tenant／environment argv | Plan 鎖 tenant、commit、Compose、environment hash；每個強制 flag 必須恰好一次且與 plan 相等 |
| 舊 output 可被覆寫重用 | Capacity、soak、cost、degradation 與 plan generator 都要求 fresh formal artifact paths |
| Evidence 可混合不同租戶／時間順序 | 總 gate 要求單一 campaign tenant、capture 早於 run、完成時間真實且 artifact 不重複 |
| Capacity spec 部分數值未 fail-closed | 完整驗證硬體、峰值、SLO、resource limit、成本與 test policy 的型別及範圍 |

## 驗證結果

- P5 automated regression：100 passed。
- Ruff：PASS。
- `git diff --check`：PASS。
- 合成完整 schema v2 evidence：PASS。
- Duplicate profile、未知 environment hash、跨 image／container、混租戶、capture 時序、
  profile overprovision、invalid telemetry 與 plan argv tampering：全部 HOLD／FAIL。

## 尚未執行的 Phase gate

正式 Lite、Standard、Enterprise 2× capacity、四種 degradation、cost live drill 與
Standard 72 小時 soak 必須在隔離、profile-sized staging 硬體上實際執行。目前共用
production 的主機不符合條件，runner 會 fail closed。只有正式 evidence verifier PASS
後，才能補做 P5 商用規模最終簽核。P6 本輪依
`decisions/P5_LIVE_VALIDATION_WAIVER_2026-08-28.md` 的明確風險接受決策開放。
