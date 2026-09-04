# Input I10-3 多路解析與語系正規化 Code Review

日期：2026-09-04
狀態：`PASS（程式與本機回歸）／待正式 Provider replay`

## 結論

低品質圖片與掃描不再只依賴單一解析結果。系統會依內容產量、OCR 使用狀態及髒文字特徵啟動替代 OCR；可設定多個具憑證的 Provider，保留每一路的模型、字數、內容雜湊及失敗紀錄，再以相同、與租戶或檔名無關的規則選出一份候選並強制進人工確認。音訊、影片逐字稿及影片 OCR 統一經 zh-TW 文字正規化，未知 Provider confidence 保持為 `null`。

## 本輪 review 發現與修正

1. 原實作只有單一 `CLOUD_OCR_PROVIDER`，第一路品質不良時沒有第二路候選。已加入有序 `CLOUD_OCR_PROVIDERS`，僅使用各自憑證存在的 Provider。
2. 多路結果若只保留最後文字會失去可稽核性。現保存候選 Provider／模型／字數／SHA-256／是否入選及安全化失敗類型，不保存密鑰或上游錯誤內容。
3. 初版繁中正規化採詞彙轉換，會把公司名稱中的「台」或一般「設備」改寫成另一用詞。已收斂為 script-only s2t，並保留既有「台」，只統一字形、不改數字與領域詞。
4. Cloud OCR 的舊測試仍期待退役模型名稱。已改成跟目前 runtime default 一致，避免測試契約漂移。

## 安全與泛化邊界

- 多路 OCR 只在低產量、髒 OCR、掃描路徑沒有 OCR 或 fallback 時啟動，避免正常文件無謂增加成本。
- 啟發式選擇不能替代 ground truth；所有替代 OCR 結果仍是 `review_required`。
- Provider 名單由能力與憑證決定，不含租戶、公司、檔名或本批五筆資料的硬編碼。
- 正式品質仍須由 I10-6 的 truth corpus 與 current-release Provider replay 簽發。

## 驗證

- `tests/test_cloud_ocr_pipeline.py`、`tests/test_scan_parse_delivery.py`、`tests/test_review_workspace.py`：25 passed。
- `tests/test_text_locale.py`、Input capability／影音相關 focused regression：先前 100 passed。
- 變更 Python 檔 `py_compile`：PASS。
- 本階段變更檔 Ruff：PASS（移除一筆測試舊 unused import 後）。

Critical／High 未處理 code finding：0。正式 Provider replay 不以本機 mock 結果替代。
