# Blind Z4 設計原則（防「先射箭再畫靶」＋防 Z3 過擬合）

**狀態**：動工（2026-08-05）  
**前置**：Blind Z3 基線凍結 **67/85 pass**（`artifacts/blind_z3/eval_z3_run.json`）；修洞僅 `z3_debug`，**不得**以 Z3 滿分宣稱 Point B。  
**語料根**：同 Z3 — `Desktop/八策` + `Desktop/客戶`  
**產物**：`artifacts/blind_z4/`（本機；原始檔不進 repo）

---

## 1. Z4 相對 Z3 的硬增量

| 規則 | 說明 |
|------|------|
| **全新 hold-out** | 排除 Z2 與 Z3 `corpus_manifest` 全部檔名（含 norm_name 去重） |
| **GT 校驗** | 標註 span／must_refuse 必須對照**入庫全文**（DB chunks 或上傳後 extract），禁止只信 pdfplumber 漏頁 |
| **一次跑分** | `gt_frozen` 後單次評測；修洞用 `z4_debug`，不回寫主集 |
| **Z3 僅回歸** | Z3 可重跑確認不回退，但**不是**泛化證明 |

其餘禁止「先射箭再畫靶」條款同 Z3 `DESIGN.md` §1。

---

## 2. 強制流程

```text
① 選語料（排除 Z2/Z3）→ corpus_manifest + authoring_catalog（僅 metadata）
② 只看 catalog 出意圖題 → intent_frozen
③ 上傳入庫 → 用入庫全文填 GT → gt_frozen
④ 一次評測 → 分類型子分；修洞不改主集
```

---

## 3. 難度配比（目標，同 Z3）

| 類型 | 比例 |
|------|------|
| A 單檔 | ≤35% |
| B 無檔名／模糊 | ≥25% |
| C 跨檔／多跳 | ≥20% |
| D 拒答 | ≥10% |
| E 易混淆／近複本 | ≥10% |

題量目標：**40–60 題**（語料約 35–45 檔；可少於 Z3，但 C/E 不得縮水）。

---

## 4. 宣稱邊界

- 可宣稱：Z3 基線 + 修洞探針 + **Z4 一次跑分**＝對未見文件的泛化證據。  
- 不可宣稱：Z2 27/27、Z3 修到滿分、或 Z4 與 Z3 同檔循環＝Point B。

---

## 5. 產出順序

1. [x] DESIGN（本文件）  
2. [x] 排除 Z2/Z3 的 corpus + authoring_catalog（40 檔；禁 Z3 norm_name + Z3 出現≥2次之客戶）  
3. [x] intent 草稿 50 題（A12/B16/C10/D6/E6）→ `intent_frozen: true`  
4. [x] 上傳入庫（40/40 completed）  
5. [x] 入庫全文校 GT → `testdata/golden/z4_blind_questions.yaml` + `gt_frozen`  
6. [x] 一次評測 → `eval_z4_run.json`：**39/50 pass**（5 fail／6 review）；見 `BASELINE_TRIAGE.md`  
