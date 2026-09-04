# 第一租戶 Product Reality Audit 缺陷修復報告

日期：2026-09-04

## 結論

報告列出的 12 項缺陷，其可由程式與部署修復的部分已完成、完成 code review，並部署至 `https://kachu.tw`。目前正式 release 為 `rta-i10-a67e937`，source commit `a67e93743f834f016dafa9b50f95590b00d2ea27`，schema head `input_i10_confidence_001`，deployment manifest `dm-52ca7b60c7a535c183ef7903`。

李永仁帳號實際看到 5 個來源、0 個處理中、0 個失敗、5 個等待人工確認；音檔已產生 20 筆逐字稿候選。一般覆核佇列由原本 122 筆降為 90 筆，結構性中間產物不再要求一般使用者逐項核准。

仍不能宣稱「語意品質已正式認證」：RTA-006 需要由人員獨立標註真實內容，系統不能拿自己的輸出當答案。這是驗收證據待補，不是仍未修的程式錯誤。

## 缺陷關閉表

| ID | 狀態 | 修復與正式證據 |
|---|---|---|
| RTA-001 | CLOSED | 正式 Ask 強制 `KNOWLEDGE_UNIT_READ_MODE=enforce`，只讀 active canonical release。 |
| RTA-002 | CLOSED | 未指定 KB 時納入租戶層級已發布的音訊、影片與圖片 Knowledge Units；明確指定 KB 時仍嚴格隔離 revision scope。 |
| RTA-003 | CLOSED | 加入中英文 n-gram／token relevance、最低相關度與標題加權；引用不再任意夾帶無關圖片。 |
| RTA-004 | CLOSED | `speaker_turn`、`video_scene`、`timeline_alignment`、`sop_conflict_report` 不進一般人工確認；正式實例由 122 降至 90。 |
| RTA-005 | CLOSED | 上傳者可一次確認低風險原始逐字稿／OCR／文件文字；高風險推論與禁止動作仍須另一位 owner。 |
| RTA-006 | CODE CLOSED / EVIDENCE HOLD | 已提供帶來源 SHA-256、標註者、時間與方法的 truth-corpus runner、CER／WER／定位／臨界欄位 Gate；尚待獨立人工真值。 |
| RTA-007 | CLOSED FOR NEW RUNS | I10 已部署；既有 5 筆來源不覆寫原始解析，已依衍生證據回填真實 capability results。第二輪新上傳會完整走 I10。 |
| RTA-008 | CLOSED | 資產狀態改以來源數計算；`系統處理中`、`等待人工確認`、`已可問答`語意分離；舊來源能力結果已回填。 |
| RTA-009 | CLOSED | 引用契約支援頁碼、段落、章節路徑、表格／儲存格、時間區間、說話者、影格與 bbox，深連結時間單位統一為毫秒。 |
| RTA-010 | CLOSED | 在正式 web 容器執行 current-release 真實 probe：7/7 PASS，且 `release_bound=true`。 |
| RTA-011 | CLOSED | Playwright 改為一次登入並重用 storage state，匿名測試獨立；文案定位改採穩定語意。 |
| RTA-012 | CLOSED FOR CHANGED FILES | 本次變更 Ruff、ESLint、TypeScript、單元測試與 build 全通過；歷史 lint 債不冒充本次新缺陷。 |

## 正式驗收證據

- 發布前資料庫備份：`/opt/enclave/backups/enclave_predeploy_rta_i10_8c7c949_20260904T101300Z.sql.gz`，已通過 `gzip -t`。
- 乾淨 release source gate：PASS；source dirty=false。
- Fresh PostgreSQL + pgvector：從零 `alembic upgrade head` PASS，head=`input_i10_confidence_001`。
- PostgreSQL 整合回歸：8/8 PASS。
- Provider 真實呼叫：main LLM、internal LLM、scan LLM、embedding、voice roundtrip、long audio、cloud OCR，共 7/7 PASS。
- 前端：ESLint PASS、TypeScript PASS、Vitest 41 files／140 tests PASS、production build PASS。
- 瀏覽器：李永仁 owner 登入成功；總覽、所有資產、人工確認、音檔詳情與 Ask 可載入；console error／warning 0。
- 音檔舊資料能力狀態：轉文字已完成 20 筆、時間碼已完成 20 筆、企業詞彙校正明確顯示有限可用，不再顯示「尚未回報」。

## 第二輪複測應有的使用者流程

1. 上傳後可離開頁面，系統在背景處理。
2. `系統處理中` 只代表機器仍在跑；完成後移至 `等待人工確認`。
3. 進入人工確認，每個來源可一次確認原始逐字稿／OCR；高風險推論保留給另一位 owner。
4. 完成必要確認後來源才成為 `已可問答`，Ask 才能引用；未確認內容不會偷跑進正式答案。
5. 回答中的證據可回到原始來源精確位置。

## 尚需人員提供的唯一品質證據

請對第二輪樣本抽取各類型至少 5 件，由非系統輸出獨立標註文字、時間點與關鍵事實，再執行 `scripts/eval_input_truth_corpus.py`。在完成前，可以說「流程與服務可用」，不可說「所有格式的語意品質已被正式證明」。
