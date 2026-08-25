# Gate 1 — 工作區與發布來源治理

日期：2026-08-25  
狀態：**PASS（治理與防呆已完成；正式發布閘門預期維持 FAIL，直到 Gate 5 產生乾淨 commit、tag 與新映像）**

## 為什麼會有這麼多檔案

盤點時 `git status --porcelain=v1 -uall` 共 221 筆：

- 106 筆已追蹤修改。
- 115 筆未追蹤檔案。
- 依實際 Docker 建置範圍計算，120 筆是部署輸入，101 筆不會進入映像。
- 專案目前共追蹤 398 個 `artifacts/` 檔案；其中很多是歷史盲測、除錯、預覽、報表或執行結果，不應與正式原始碼混成同一種發布證據。
- 追蹤中的 artifact 檔名有 8 筆帶履歷、稅務、合約等敏感語意。此數字只代表需人工分類，不代表檔案內容已被判定為個資。
- 對全體已追蹤檔案進行高信度 private key／OpenAI／AWS／GitHub／Slack 憑證樣式掃描，命中 0 筆。掃描器不會輸出憑證原文。

目前變更最多的區域是 `app`（77）、`frontend`（38）、`scripts`（30）、`tests`（29）、`artifacts`（17）、`docs`（15）。因此不能把所有變更不分類地部署，也不能假設它們都不需要；真正的做法是讓映像只使用明確 allowlist，並讓發布閘門驗證那份 allowlist 的每一個 hash。

## 已完成的治理

1. `scripts/freeze_deployment_manifest.py` 的部署 allowlist 目前共 474 個檔案：backend 331、frontend 130、gateway 13；`artifacts`、測試語料與本機輸出不在 Docker 部署輸入內。
2. 新增 `scripts/release_source_gate.py`，採 fail-closed 檢查：
   - 工作區必須完全乾淨。
   - manifest 的 commit 必須等於 HEAD。
   - HEAD 必須有 release／RC tag。
   - 474 個部署檔案的路徑、群組、大小與 SHA-256 必須完全一致。
   - backend 與 frontend 必須綁定合法的 immutable image ID。
   - manifest 不得從髒的部署來源產生。
   - 所有 Git 已追蹤檔案不得命中高信度憑證樣式。
3. `.gitignore` 已排除每次執行產生的 `*_last_run.json`、handoff bundle、候選 manifest、ops dry-run、migration SQL、開發探測與檢查文字；基準資料及人工校對資料仍需明確審核後才能納管。
4. 發布閘門只回報憑證類型與檔案路徑，不會把疑似秘密印到 log 或 JSON。

## 檔案處置規則

| 類型 | 正確位置 | 是否進 Git | 是否進映像 |
|---|---|---:|---:|
| 應用程式、migration、前端、gateway | 既有 source tree | 是 | 依 allowlist |
| 自動化測試與合成 fixture | `tests/` | 是 | 否 |
| 架構、操作與決策文件 | `docs/` | 是 | 否 |
| 每次測試／稽核執行結果 | `artifacts/` 或外部證據庫 | 否 | 否 |
| 密封盲測題庫 | 獨立保管人／唯讀證據庫 | 否 | 否 |
| 客戶文件、上傳內容、備份、逐字稿 | 正式資料儲存與備份系統 | 絕不 | 絕不 |
| 候選映像 | image registry，以 digest 保存 | 否 | 本身即交付物 |

## Code review

Review 先發現兩個問題並已在本關修正：

1. 腳本以 `python scripts/release_source_gate.py` 直接執行時 import 路徑錯誤；已加入直接執行相容處理並實跑確認。
2. 憑證掃描原先只涵蓋 474 個映像輸入；已擴大為所有 Git 已追蹤檔案，避免文件、測試或腳本夾帶憑證。
3. manifest 原先只核對路徑；已增加 backend／frontend／gateway 群組一致性檢查。
4. 測試用假 token 改為執行期組合，避免之後 Git 追蹤測試檔時被正式掃描器正確攔下。

驗證結果：`tests/test_release_source_gate.py` 與 `tests/test_deployment_manifest.py` 共 8 項通過。以目前工作區執行正式閘門會正確得到 FAIL（工作區不乾淨、舊 manifest 由髒來源建立），這是必要的阻擋，不可略過。

## 後續 Gate 5 的強制完成條件

- 將必要 source、tests、docs 與 migration 整理成可重建的 commit。
- 將不該由 Git 納管的執行 artifact 移出版本來源；若歷史已含真實敏感內容，另立受控的 history-remediation 工作，不在未通知協作者的情況下改寫遠端歷史。
- 建立 RC tag，從該 tag 建置新 backend/frontend images。
- 重新凍結 manifest，執行 `release_source_gate.py` 必須 PASS。
- 產生 source commit、tag、manifest ID、image digest 與 SBOM 的一對一發布表。
