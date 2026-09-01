# Production Provider Runtime Gate Acceptance — 2026-09-01

## 結論

`https://kachu.tw` 已部署並驗收 Provider runtime gate，正式 release 為
`production-providers-bebbdd3`。

- Source：`bebbdd386e8b802493d6ed12f50a8c8be2426ecd`
- Deployment manifest：`dm-fb5bb414335248177f1d0448`
- Schema：`input_i8_pilot_evidence_001`
- Route contract：`5af2bf671476e71a40b148d374217000cf5271c648b6a96e7632e5ddb525b69f`
- Production verification：15／15 PASS
- Required Provider live gate：7／7 PASS

## 正式 live gate

下列結果均來自新正式容器的真實呼叫，不是設定檔存在性檢查：

| 能力 | Provider／模型 | 結果 |
|---|---|---|
| AI 問答 | OpenAI `gpt-5.6-luna` | PASS |
| 內容整理與分類 | Gemini `gemini-3.6-flash` | PASS |
| 掃描內容理解 | Gemini `gemini-3.6-flash` | PASS |
| 知識檢索索引 | Ollama `bge-m3`，1024 維 | PASS |
| 語音辨識與語音輸出 | OpenAI TTS → `gpt-transcribe` | PASS |
| 長時間錄音與說話者辨識 | OpenAI `gpt-4o-transcribe-diarize` | PASS |
| 圖片與掃描文件 OCR | Gemini `gemini-3.6-flash` | PASS |

現有 production OpenAI／Gemini 憑證已足夠，本次未讀取
`C:\Users\User\Desktop\api key.txt`，也未把任何憑證寫入程式碼、文件、log 或 commit。

## 發布保護

- 部署前資料庫備份已建立並通過 gzip 完整性與非空檢查：
  `/opt/enclave/backups/enclave_predeploy_d40b4de_20260901T025000Z.sql.gz`。
- 舊版 image 保留，可用於 rollback；`.env.production` 另有部署前備份。
- Web、worker、worker-beat、frontend 與 gateway 使用同一正式 release identity。
- `/health` 與 `/release.json` 的 source、manifest、schema 及 route contract 一致。

## 瀏覽器驗收

以公開合成「公司管理」角色完成登入後驗收：

- Owner／admin 可讀取七項外部服務設定，不再遇到錯誤的 superuser-only 403。
- 公開 Demo 受既有 middleware 保護，不執行付費 live probe；按鈕明確停用並說明。
- 真實非 Demo 租戶 owner／admin 可明確按下 live probe；頁面載入不會自動產生 API 用量。
- 桌面版資訊層級與狀態清楚，console error／warning 為 0。
- 390×844 窄螢幕 `scrollWidth=clientWidth=390`，無頁面水平溢位。

## 尚未完成的首租戶工作

本驗收證明 production 平台與必要 Provider 可用，不等於八策股份有限公司的真實資料已完成驗收。仍需要：

1. 兩位具名使用者的姓名與公司 Email，並指定其中一位為 owner。
2. 決定八策採專屬 deployment／database，或接受受控 Pilot 暫行資料邊界；目前 production 尚有合成 Demo tenant，FORCE RLS rollout 仍未完成。
3. 提供代表性文件、圖片、音檔與影片，執行 Input → review → publish → retrieval → citation 的真實端到端驗收。
