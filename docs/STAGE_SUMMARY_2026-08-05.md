# Enclave 階段性總結報告

**日期**：2026-08-05  
**範圍**：Point A → Point B 推進至 Blind Z4 收束  
**狀態**：Blind Z 系列本輪可收；整體 Point B **未宣稱達成**  
**對應文件**：`docs/VISION_POINT_A_TO_B.md`、`docs/OPEN_GATES.md`、`artifacts/blind_z3/`、`artifacts/blind_z4/`

---

## 1. 一句話結論

Enclave 已具備「可入庫、可檢索、可拒答、可重跑驗收」的產品骨架；對**未見過文件**的答題實力，以兩輪獨立盲測估計約 **78–79%**。架構完成度約 **75–85%** 朝向 Point B，但**還不能對外宣稱「敢讓客戶亂丟亂問都穩」**。

---

## 2. 目標是什麼（Point B）

文件定義（`VISION_POINT_A_TO_B.md`）：

> Enclave 變成一個敢讓客戶亂丟文件、亂問問題的產品——上傳各種合約、掃描、表單、手冊之後，AI 問答的正確性、穩定性、可解釋性是**架構撐住的**，不是靠 prompt 或運氣。

本階段要回答的不是「黃金集能不能滿分」，而是：

1. 換一批**系統沒練過、出題時沒偷看內文**的真實客戶／八策文件，還能不能答？  
2. 答錯時是**產品洞**還是**標註錯**？  
3. 修洞後能不能用**探針**證明修好，同時**不把舊考卷刷滿分當成達標**？

---

## 3. 我們怎麼辦到的（方法論）

### 3.1 硬約束：禁止「先射箭再畫靶」

全程遵守：

| 規則 | 做法 |
|------|------|
| 先出題、後看答案 | 只看 catalog（客戶名／檔名／類型），**不開檔內文**寫意圖題 → `intent_frozen` |
| GT 必須對得上入庫全文 | Z4 強制用 DB chunks 標 span；禁止只信 pdfplumber 漏頁 extract |
| 分數一次凍結 | `gt_frozen` 後單次評測；結果寫入 `eval_z*_run.json` **不可事後改主集分數** |
| 修洞另開探針 | 修完用 `z*_debug_*.json` 驗證；**不得**用修後滿分宣稱 Point B |
| 新語料 hold-out | Z4 排除 Z2／Z3 已用檔名與高頻客戶，避免過擬合 |

### 3.2 整體施工流程（可重跑）

```text
① 選語料 hold-out（雙根：Desktop/客戶 + Desktop/八策）
② 只看 metadata 寫意圖題 → intent_frozen
③ 上傳 API → Celery 入庫（RAGFlow + 必要時 Gemini OCR）→ 等 completed
④ 匯出入庫全文 → 標 GT → gt_frozen
⑤ 一次跑分 scripts/eval_answer_correctness.py（API :8011）
⑥ 人工／腳本複核 fail／review → BASELINE_TRIAGE.md
⑦ 修產品洞 → 單元測試 + 單題探針（不回寫主集）
⑧ 更新 VISION／OPEN_GATES 宣稱邊界
```

### 3.3 基礎設施怎麼撐住評測

- **API**：Docker Compose `web` 對映本機 **8011**（避開 ForgeBase 佔 8001）。  
- **帳密**：`admin@enclave.local`／評測腳本登入後打 `/chat` 串流。  
- **入庫**：`process_document_task`；OCR 慢時曾卡 `uploading`／`embedding`；處理方式為提高 worker 並行、清 chunk UniqueViolation 後重派、有完整 embedding 者可 force completed。  
- **判分**：答案須含 GT `span_contains`；`must_refuse` 須出現拒答標記。部分命中 → `review`。

### 3.4 複核怎麼分「真洞」與「假紅」

對每題 fail／review：

1. 讀系統答案與召回檔名；  
2. 對照 **DB `documentchunks.text`**（不是只看本機 extract）；  
3. 分類：產品洞／GT 過嚴／題答不匹配／OCR 弱。  

例：Z3 部分 `must_refuse` 題，extract 沒價但入庫有價 → **標註過嚴，不是幻覺**。  
例：Z3-036 題問雙方／類型，GT 卻是金額 → **標註錯**，分數仍凍結保留 fail 標籤以維持方法誠實。

---

## 4. 盲測成績一覽（證據）

| 輪次 | 語料 | 題數 | 正式分數 | 產物 | 可宣稱？ |
|------|------|------|----------|------|----------|
| Z2 | 8 檔、偏「根據《檔名》」 | 27 | **27/27** | 歷史修洞迴圈 | **否**（方法弱、修後同集滿分） |
| Z3 | 55 檔 hold-out | 85 | **67 pass／3 fail／15 review** | `artifacts/blind_z3/eval_z3_run.json` | 可作泛化基線之一 |
| Z4 | 40 檔全新 hold-out | 50 | **39 pass／5 fail／6 review** | `artifacts/blind_z4/eval_z4_run.json` | 可作第二輪泛化證據 |

**口徑**：

- 可宣稱：未見文件上約 **78–79%** 一次跑分；拒答紀律（Z4 的 D 類）**6/6**。  
- 不可宣稱：Z2 滿分＝Point B；修洞後把 Z3／Z4 刷滿分＝達標。

---

## 5. 各階段做了什麼

### 5.1 地基與編排（較早完成）

- FOUNDATION F0–F4、FD-* 五閘門 PASS（入庫交付、Catalog、融合、QueryPlan、條款投影）。  
- MultiStepOrchestrator／ToolRouter／拒答／Trace。  
- 對抗集 8/8；主黃金集曾 40/40（易飽和，**不當唯一鐵證**）。

### 5.2 Blind Z3（第一輪認真泛化）

**怎麼做：**

1. 雙根選 55 檔 → catalog → 意圖題 85 → 上傳入庫。  
2. GT 初期含 extract＋掃描視讀；後用 DB 複核發現多題 GT 過嚴。  
3. 一次評測凍結 **67/85**。  
4. 複核寫入 `BASELINE_TRIAGE.md`；願景文件降級「Z2 不得當 Point B」。

**修過的產品洞（z3_debug，不改主分）：**

| 洞 | 根因 | 修法 |
|----|------|------|
| Catalog 中文檔名漏列 | token 只抽拉丁 | `_filename_tokens` 抽 CJK＋引號 |
| 問金額無數字仍瞎答 | 缺證據門檻 | `amount_question_lacks_numeric_evidence` |
| 「」點名檔 miss 卻廣搜他檔 | scoped 失敗仍 fallback | 點名 miss → 禁止跨檔頂替 |
| 保證題用他處日期頂替 | 無「保證」字仍答 | `guarantee_question_lacks_evidence` |
| 跨檔比價拆解弱 | 顿号／「哪份較高」 | QueryPlan 1.3＋scoped 軟匹配 |

### 5.3 Blind Z4（第二輪、方法更嚴）

**怎麼做：**

1. `scripts/build_blind_z4_corpus.py`：排除 Z2 關鍵字、Z3 norm_name、Z3 出現≥2 次客戶 → **40 檔**。  
2. 只看 `authoring_catalog.json` 寫 **50 題**意圖（A12/B16/C10/D6/E6）→ `intent_frozen`。  
3. `upload_blind_z4.py` 上傳 40/40；輪詢至 completed（期間處理佇列卡住、UniqueViolation、OCR 長尾）。  
4. `export_blind_z4_ingested.py` 匯出 DB 全文 → `annotate_blind_z4_gt.py` 標 GT → **`gt_frozen`**。  
5. 一次評測凍結 **39/50**；`BASELINE_TRIAGE.md` 分類 fail／review。  
6. 願景／OPEN_GATES 寫入 Z4 數字與宣稱邊界。

**Z4 正式 fail 與後續修洞（探針，不改 39/50）：**

| 題 | 現象 | 怎麼修 | 探針 |
|----|------|--------|------|
| 017／020／046 | 已找對檔仍「金額過拒」 | 拒答前 `amount_expand` 補文件頭；放寬金額 regex | 017／020 **pass**；046→review |
| 009 杏壺 | 有 `每月45,000` 卻答成效 ROAS | 辨識裸檔名 `*.pdf`；金額段落提前 | **009b pass** |
| 028 金正昌 | 語意廣搜撈到別家「提案」 | fact 題也跑 catalog；token 命中檔名 → 強制 scoped | **028b pass** |

---

## 6. 目前能力水位（對你目標的對照）

| 面向 | 估計 | 說明 |
|------|------|------|
| 產品骨架 | ~90%+ | 入庫／多粒度檢索／編排／拒答／可重跑閘門 |
| 未見文件答題 | ~78–79% | Z3＋Z4 一次跑分同量級 |
| 拒答紀律 | 高（本輪） | Z4 D 類全過；仍需防過拒與漏拒 |
| Point B「敢亂問」 | **未達標** | 仍有找錯檔、漏關鍵金額、跨庫干擾等 |
| 商業閉環 | 程式近完、人工閘門開 | 外部滲透為主；OAuth／法律／DR 另列 |

**白話**：內部示範與試用可以；說「隨便丟隨便問都穩」還不行。

---

## 7. 計畫與閘門狀態（截至本報告）

| 項目 | 狀態 |
|------|------|
| 可驗證 code 出口 | 100%（計畫內 code 項） |
| FD-*／VISION-ADV／CEILING | PASS |
| Blind Z3／Z4 基線 | 已凍結並複核 |
| 剩餘出口 checkbox | **外部滲透測試**（需第三方） |
| 本機 SKIP | SharePoint／Google Drive OAuth |
| 其他人工 | 法律授權審查、客戶現場 DR 簽核 |

細節：`docs/OPEN_GATES.md`。

---

## 8. 關鍵產物路徑

| 用途 | 路徑 |
|------|------|
| 願景總綱 | `docs/VISION_POINT_A_TO_B.md` |
| 開放閘門 | `docs/OPEN_GATES.md` |
| Z3 設計／分數／複核 | `artifacts/blind_z3/`（含 `eval_z3_run.json`、`BASELINE_TRIAGE.md`） |
| Z4 設計／分數／複核／入庫全文 | `artifacts/blind_z4/`（含 `eval_z4_run.json`、`ingested_text/`、`BASELINE_TRIAGE.md`） |
| Z3／Z4 題庫 | `testdata/golden/z3_blind_questions.yaml`、`z4_blind_questions.yaml` |
| 評測腳本 | `scripts/eval_answer_correctness.py` |
| 選檔／上傳／標 GT | `scripts/build_blind_z4_corpus.py`、`upload_blind_z4.py`、`export_blind_z4_ingested.py`、`annotate_blind_z4_gt.py` |

原始客戶／八策檔**不進 git**；評測產物留本機 `artifacts/`。

---

## 9. 誠實邊界與下一步建議

**本階段結束條件（已滿足）：**

- 兩輪 hold-out 盲測有凍結分數與複核；  
- 主要產品洞有修法＋探針；  
- 文件已寫清「能／不能宣稱什麼」。

**若要再逼近 Point B（建議優先序）：**

1. 新 hold-out（Z5）驗證修洞是否泛化，**禁止**只重跑 Z3／Z4 主集當證明。  
2. 壓「全庫舊客戶干擾盤點題」（Z4-037 review 類）。  
3. 表格／掃描 OCR 金額穩定度。  
4. 外部滲透與上線憑證（非答題主線，但是商業閉環必要）。

---

## 10. 給決策者的摘要

1. **怎麼辦到的**：用「凍結意圖 → 真實入庫 → 入庫全文標答案 → 一次跑分 → 複核分類 → 探針修洞」的閉環，刻意防止刷題達標。  
2. **現在多強**：未見文件約八成；骨架齊；Point B 未到。  
3. **值不值得信任**：值得當**可控試用**；不值得當**已保證正確的黑盒**。  
4. **本輪可收**：Blind Z 系列階段性工作可結束；剩餘多為外部人工閘門與下一輪新語料驗證。

---

*報告撰寫：依 2026-08-05 當日倉庫狀態與 `eval_z3_run.json`／`eval_z4_run.json` 凍結分數；後續若重跑主集，以當次 artifact 為準，但不得回溯改寫本報告所引用之凍結數字含義。*
