# 標註檢查清單（填 GT 前必讀）

1. 使用 **`intent_questions_draft_v3.yaml`**（勿用 v1／v2）。
2. 先確認 `meta.intent_frozen: true`（題幹鎖定後才標）。
3. **只**依 `evidence_hint` 的 doc-id 對 `authoring_catalog.json`／`corpus_manifest.json` 打開**原始**檔（路徑在 `八策` 或 `客戶`）。
4. 答得出：填 `expected_spans`（預列合法變體）；答不出：`must_refuse: true`，**不改題幹**。
5. 另存 `z3_blind_questions.yaml`，設 `gt_frozen: true`。
6. 禁止為分數改題／放寬 span；錯標用 `gt_errata`。

禁止：邊標邊開 Enclave；出題或改題時讀 `extracts/`。  
extracts 僅原檔打不開時輔助，且須 errata 註明。
