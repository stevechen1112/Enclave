# Input I8 第一租戶受控 Pilot Runbook

## 目的與邊界

本 runbook 用於以真實租戶、人員、裝置、網路及資料，執行 14–28 天的 Input 現場試行。內部自動化測試、synthetic corpus 或人工補寫報告均不能替代此 gate。

Pilot PASS 只代表約定範圍內的受控驗收通過，不等於共享多租戶 GA、24/7 SLA、跨產業準確率或高風險自動控制能力。

## 啟動前條件

1. 使用專屬 deployment 或 database，並保存環境設定輸出的 SHA-256。
2. DPA、資料保留／刪除、外部 AI provider、事件通報及支援窗口均已簽妥。
3. 選定 2–3 條 journey：NAS 批次、文件批次、長時間錄音、機台影片。
4. 每條 journey 必須有本租戶有效覆核人、metadata 模板、術語表版本及角色／ACL 參照。
5. 約定 success、retry、人工修正、processing p95、引用率與最少／最多觀察天數。
6. 管理員在「系統 → Input 試行」建立 Pilot；只能以 `live` evidence 進入正式 gate。

## 每日執行

- 管理員從「系統 → Input 試行 → Pilot 證據工作台」直接登錄證據；不需再以手動 API 指令完成日常流程。
- 每個已設定 journey、每個觀察日各提交一筆不可覆寫的 daily metric。
- 指標來源報表必須封存，系統只登錄其 SHA-256；不得以任意字串代替實際證據。
- 記錄 total/successful attempts、retry、人工修正、processing p95、retrieval/citation 與 friction。
- 發生資料遺失、越權、假完成或 near miss 時立即建立 incident，不得等到期末補登。
- 不可提交 Pilot 開始前、未來日期、最大觀察期間外或未設定 journey 的指標。

## Incident 與稽核

- 工作台列出未結 Incident；root cause、corrective action 與 retrospective SHA-256 齊備後才開放結案按鈕。
- Incident 必須完成 root cause、corrective action 及 retrospective 檔案 SHA-256，狀態才可改為 resolved。
- quality、security、permission 三類 audit 都必須完成；最新一次結果才是 gate 的權威結果。
- 標記 `pass` 的 audit 必須有實際抽樣數，且證據時間不可早於 Pilot 開始或晚於現在。
- 發現新 incident 或最新 audit 失敗時，即使先前曾顯示 PASS，也必須視為 HOLD 並重新處理。

## 結案與簽署

1. 確認 14–28 天資料連續、所有 journey 每日都有資料且 SLO 全部達標。
2. 確認所有 incident 已關閉，三種最新 audit 均通過。
3. 封存整體 retrospective，登錄檔案參照及 SHA-256。
4. 由系統執行 acceptance preflight；HOLD 時不得接受簽署。
   - 若唯一 blocker 是 `signed customer acceptance is missing`，工作台會顯示「preflight 已就緒」，後端仍會在寫入時重驗。
5. 使用 `docs/templates/INPUT_PILOT_ACCEPTANCE_TEMPLATE.md` 產出文件，由客戶授權人簽署後登錄文件參照、SHA-256 與簽署時間。
6. 最終 gate 顯示 PASS 後，才可討論擴大租戶或 GA；仍需另外完成 I7 live capacity gate。

## HOLD 處理

- 不得刪除或覆寫既有證據來消除失敗；建立新的 audit 或新 Pilot。
- daily metric 重複鍵回傳 409，代表不可覆寫，不是重試失敗。
- 若一開始的 journey、ACL、術語表或環境錯誤，關閉本次試行並建立新的 Pilot，不重設開始時間污染原 ledger。
- DPA、專屬環境與簽署文件目前以 reference + SHA-256 attestation 保存；實際文件存在性與簽署權限須由導入負責人外部核對。

## 現階段尚未完成

- 尚未建立真實第一租戶 Pilot。
- 尚未累積 14–28 天 live evidence。
- 尚未取得客戶簽署 acceptance。
- I7 的 2× live capacity、degradation drills 與 72 小時 soak 仍為 HOLD。
