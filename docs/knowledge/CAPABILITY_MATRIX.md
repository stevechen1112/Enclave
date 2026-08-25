# 文件與語言能力矩陣

「處理完成」只表示流程已結束；是否能回答由每份文件的 capability readiness 決定。

| 格式／內容 | 等級 | 可用能力 | 使用者應採取的動作 |
|---|---|---|---|
| TXT、Markdown、文字型 PDF、DOCX | supported | catalog、narrative；表格／程序依實際結構 | 抽查來源定位 |
| CSV、XLSX | supported | catalog、narrative、structured rows | 發布前抽查 identity 欄與至少 30 rows／5 files |
| 掃描 PDF | limited | OCR 通過後才可 narrative | 檢查低信心頁、頁序與表格斷裂 |
| PPTX | limited | 文字敘事 | 圖表、流程圖需人工確認 |
| 圖片 | experimental | OCR 文字 | 不把圖形關係當正式證據 |
| 錄音 | experimental | transcript；先 provisional | 校對、標 speaker、核准後才可一般問答 |
| 手寫 | unsupported | catalog only | 人工轉錄或提供可辨識版本 |
| CAD／工程圖 | unsupported | catalog only | 不宣稱能理解尺寸與圖面關係 |

語言：繁中、英文與中英混合為目前主要驗證範圍；料號、縮寫另以 code token 保存。其他語言若未通過相同格式與題型矩陣，一律顯示「尚未驗證」，不得因 parser 能抽字就宣稱支援。
