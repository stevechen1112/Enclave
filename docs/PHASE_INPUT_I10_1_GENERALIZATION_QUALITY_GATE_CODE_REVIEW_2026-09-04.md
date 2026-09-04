# Phase Input I10-1：泛化品質 Gate Code Review

狀態：`PASS FOR I10-1 IMPLEMENTATION / PRODUCT REMAINS HOLD`

日期：2026-09-04

## Review 範圍

- `app/services/input_quality.py`
- `scripts/eval_input_i4_corpus.py`
- `scripts/eval_input_i5_corpus.py`
- `tests/test_input_generalization_quality.py`
- `tests/test_input_i4_corpus_evidence.py`
- `tests/test_input_i5_media_productization.py`
- I4／I5 evidence report 的 certification metadata

## Review 結論

本次實作達成 I10-1 的核心目的：測試執行成功與產品品質認證已分離；證據類型會限制可宣稱層級；required slice、樣本數、ground truth、單筆失敗、關鍵欄位與 no-content outcome 均有 fail-closed 行為。

Review 過程抓到並修正一個 evaluator 自身缺陷：通用文字正規化會移除小數點，可能將 `6.5 BAR` 與 `65 BAR` 判為相同。關鍵欄位現改用保留標點、只折疊 Unicode 與空白的 exact match。

## 驗證結果

| 檢查 | 結果 |
|---|---|
| I10 泛化品質與 production audit 單元測試 | 12 passed |
| I4 原品質函式、corpus evidence、I5 media productization 回歸 | 35 passed |
| 合計 focused pytest | 47 passed |
| Python compile | PASS |
| Ruff | PASS |

覆蓋的關鍵反例：

- synthetic 完全正確仍只能到 mechanical，semantic 為 HOLD；
- required slice 缺失使全體 HOLD；
- 單一錯誤不可被九筆成功的平均值隱藏；
- 關鍵數值小數點遺失會 FAIL；
- 已人工驗證的無語音影片可回傳 `no_speech`，不誤判為 parser failure；
- unknown confidence 與 measured zero 分離；
- Wilson 95% interval 顯示小樣本不確定性。

## 尚未關閉的產品風險

- 真實 5 筆來源尚未建立人工 ground truth；
- production review／publish／Ask／citation 尚未完成；
- 本機 I4 replay 揭露 Tesseract runtime 缺失，報告尚未全面綁定環境指紋；
- OCR／ASR confidence 尚未校準；
- production audit 尚未游標化，不適合作為大租戶全量掃描器；
- review workspace、來源層級發布與 Ask serving truth 的既有缺陷仍待 I10-4／I10-5 修復。

因此，本 Code Review 只批准 I10-1 共用品質 Gate，不批准產品 Ready，也不把 I10 後續 Phase 視為完成。
