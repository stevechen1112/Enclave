# P5 商用規模 Live Validation 本輪豁免決策

日期：2026-08-28

決策：產品負責人明確要求本輪先略過 P5 的三種 deployment profile 容量測試、
live degradation drill 與 72 小時 soak，直接進行 P6。

## 邊界

- 本決策只解除產品化開發順序的阻擋，不把未執行測試改寫成 PASS。
- P5 程式、runner、telemetry、evidence schema v2、fail-closed gate 與內部 Code
  Review 維持 `COMPLETE`。
- 尚未執行的正式 live evidence 維持 `WAIVED / NOT RUN`，不得用於對外宣稱
  Lite／Standard／Enterprise 容量、72 小時穩定性或故障復原 SLO。
- production 不承受本輪壓力測試或故障注入。
- P6 可開始；P7／P8 若要形成商業 GA 認證，必須重新檢視此豁免是否仍可接受。

## 後續補驗項目

1. Lite／Standard／Enterprise 各一份隔離、profile-sized 2× capacity evidence。
2. provider slow、quota exhausted、queue saturated、sidecar unavailable live drill。
3. Standard 72 小時 soak 與成本 guardrail live evidence。
4. Evidence verifier PASS 後補做 P5 商用規模最終簽核。

此文件是風險接受紀錄，不是測試結果。
