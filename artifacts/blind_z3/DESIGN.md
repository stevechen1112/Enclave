# Blind Z3 設計原則（防「先射箭再畫靶」）

**狀態**：原則有效；語料改為雙根並重置題庫（2026-08-05）  
**語料根目錄**：
- `C:\Users\User\Desktop\八策`
- `C:\Users\User\Desktop\客戶`  
**產物**：`artifacts/blind_z3/`（本機；原始檔不進 repo）  
**現行題庫草稿**：`intent_questions_draft_v3.yaml`（對齊 `authoring_catalog.json`）  
**作廢**：v1（contaminated）、v2（單根、已由雙根取代）

詳見 `REVIEW.md`。

---

## 1. 什麼叫「先射箭再畫靶」（禁止）

| 禁止行為 | 為何假綠 |
|----------|----------|
| 先看 extract／系統回答再命題或改 span | 題庫追模型／追可抽字串 |
| 捏造 hold-out 沒有的檔名再當可答題 | 腦補畫靶 |
| 修洞後用同一失敗集當唯一滿分 | 評測集過擬合 |
| 檔名已洩漏答案大半仍當難題 | Z2 式膨脹 |

---

## 2. 強制流程

```text
① 凍結語料清單（authoring_catalog：client/name/stratum only）
② 出題：只看 catalog，不開檔、不讀 extracts/
③ intent_frozen → 標註：只看原檔填 GT
④ gt_frozen → 一次評測；修洞用 z3_debug，不回寫主集
```

---

## 3. 難度配比（目標）

| 類型 | 比例 |
|------|------|
| A 單檔 | ≤35% |
| B 無檔名／模糊 | ≥25% |
| C 跨檔／多跳 | ≥20% |
| D 拒答 | ≥10% |
| E 易混淆／近複本 | ≥10% |

---

## 4. 語料選取（現行）

- 腳本：`scripts/build_blind_z3_corpus.py`（雙根、去重、分層、排除 Z2 檔名）
- `corpus_manifest.json`：約 55 檔（客戶為主、八策內部／補助／辦公室約為輔）
- `authoring_catalog.json`：**出題唯一允許依據**
- `extracts/`：出題禁用（見目錄內 BAN）

---

## 5. 判分與宣稱

- 主判：`span_contains`／`must_refuse`
- 可預列合法變體（標註時）；禁事後追模型改 span
- 可宣稱：題幹凍結後一次跑分＋分類型子分  
- 不可宣稱：修洞循環至 100%＝Point B；Z2 27/27 單獨證明 Point B

---

## 6. 產出順序

1. [x] DESIGN／REVIEW  
2. [x] 雙根 corpus + authoring_catalog  
3. [x] intent v3（無 span）  
4. [x] `intent_frozen: true`  
5. [x] 標註 GT → `testdata/golden/z3_blind_questions.yaml`（`gt_frozen: true`）  
6. [x] 上傳 55 檔 hold-out 與**一次**評測 → `eval_z3_run.json`：**67/85 pass**（見 `BASELINE_TRIAGE.md`）  
7. [x] 修洞用 `z3_debug`（catalog／拒答／比價）；**主集 67/85 凍結**；下一正式驗證為 **Z4**（見 `artifacts/blind_z4/`）  

**標註來源**：pdfplumber／docx 獨立抽取＋掃描件 `page_previews` 視讀；未呼叫 Enclave chat。  
無法可靠讀取之掃描／無總價提案：標 `must_refuse`（誠實不可答，非放寬）。
