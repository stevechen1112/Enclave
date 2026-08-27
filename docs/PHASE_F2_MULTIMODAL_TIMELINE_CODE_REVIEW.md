# Phase F2 Code Review：多模態時間軸理解

**Review date**: 2026-08-26
**Gate result**: PASS（完成下列修正後）

## Review 範圍

- provider-neutral `TimelineObservation` / `MultimodalUnderstandingProvider` contract。
- FFmpeg scene boundary provider、ASR speaker passthrough、保守的動作/設備狀態候選。
- 專業說話者分離與異常聲音 provider 未啟用時的 fail-closed 語意。
- 鏡頭、逐字稿、OCR、畫面、說話者、動作與設備狀態的時間窗對齊。
- provider failure isolation、冪等 artifact identity、schema migration 與前端候選顯示。

## 發現與修正

1. **[High] 逐字稿、OCR 與關鍵幀原本沒有進入 alignment bundle**
   - 修正：從同一 revision 的 EvidenceSpan 加入三類原始 artifact，以 scene 範圍（無 scene 時 30 秒窗）建立可追溯 `windows`。
2. **[High] provider 結果後到可能用 unavailable 覆蓋 available**
   - 修正：capability state 以明確優先序合併，低品質/不可用狀態不得降級已成功的 provider。
3. **[High] artifact lineage 原本只有 `core.video`，會遺失真正分析 provider**
   - 修正：DerivedArtifact 保留 observation provider/version，規則候選也清楚標記 `core.evidence_rules`，不冒稱模型辨識。
4. **[Medium] 後續重新分析可產生新 alignment artifact，UI 可能取到舊版**
   - 修正：artifact 仍保持 immutable；Review UI 明確取該 revision 最新 alignment，舊產物保留供稽核。
5. **[Medium] `%` 單位因 word-boundary 規則不會命中**
   - 修正：改為 negative word lookahead，數值單位候選可支援 `%`。
6. **[Medium] 服務內硬編碼 provider 將阻礙租戶專屬模型**
   - 修正：新增 composition root，未來專業 diarization/action/audio model 可以 provider 方式插入，不改核心管線。

## 語意保證

- `speaker_diarization=available_upstream` 只在上游實際回傳 speaker label 時出現；系統不自行發明說話者。
- `action_event` / `equipment_state=candidate_rules` 是有原文證據的規則候選，不宣稱為視覺動作模型。
- 本地 provider 只輸出 `candidate_signal_outlier`：以影片自身一秒 RMS 中位數基準找聲學離群，明確標記 `semantic_diagnosis=false`。它不會把大聲直接說成軸承或機台故障；語意異常類型仍需租戶核准的專業 provider。
- 所有候選均是 `review_required`，不會繞過 F3 治理發布。

## 驗證證據

- F2/F1 專屬測試：14 passed，包含 scene 分段、不偽造 speaker、provider failure isolation、精確 EvidenceSpan 與跨模態 window。
- Asset/Ingestion/Retrieval 相關回歸：48 passed。
- Frontend：69 passed；production build 與 ESLint 通過。
- PostgreSQL：F2 downgrade/upgrade 往返與 `alembic check` 通過。

## 下階段入口

F2 只封板事件與對齊層。候選內容尚不得發布為正式作業知識；F3 必須完成條件/規則/風險/例外結構、正式 SOP 衝突檢查、衝突處置與發布門檻。
