# Provider Runtime Gate — Code Review（2026-09-01）

## 範圍

本階段只處理首租戶所依賴的外部／模型服務可用性，不改變租戶資料、知識內容或應用模組：

- 主問答 LLM。
- 內部分類／整理 LLM。
- 掃描內容理解 LLM。
- 知識檢索 embedding。
- 短語音 TTS → STT round trip。
- 長音檔說話者辨識 STT。
- 圖片／掃描文件 Cloud OCR。

## Review 結論

**PASS，可進入正式環境部署與實測。**

### 已確認

1. Provider 設定查詢不回傳 API KEY，只回傳角色、服務商、模型、啟用狀態與「憑證是否存在」。
2. 真實 API 呼叫只允許具 `system_ops` 的租戶 owner／admin（含 platform superuser）以 `POST` 明確觸發；開啟健康頁或重新整理不會產生付費呼叫。
3. 七個角色任一未啟用、未設定憑證、回傳空白或呼叫失敗，整體 gate 都會 fail closed。
4. UI 錯誤內容經過收斂，不轉送 Provider response body、URL、header 或憑證。
5. Gemini 預設模型已由失效／過期名稱統一更新為實際驗證可用的 `gemini-3.6-flash`。
6. Production 範本明確指定 internal、scan 與 Cloud OCR，避免無 GPU 主機誤連不存在的 host Ollama。
7. CLI 可在部署後產生 JSON 證據並以 exit code 阻擋不完整的 Provider 組合。

## 測試證據

- Provider gate、空白回應、錯誤去敏、POST／superuser contract：5 passed。
- Deployment fallback 與 sidecar runtime regression：15 passed。
- 合計相關後端：20 passed、0 failed。
- 前端 Provider gate：1 passed，且證明 page load 不會呼叫 probe。
- TypeScript／Vite production build：PASS。
- ESLint：PASS。
- Ruff 與 `git diff --check`：PASS。
- 正式環境先行合成 OCR probe：Gemini `gemini-3.6-flash` 回傳非空且正確命中 `8246` 錨點。
- 正式 live gate 首輪發現 Gemini 3.6 在 16-token probe 額度下可能成功但無可見文字；以 128-token 重測 internal／scan 均回傳 11 字元。Probe 已修正並新增回歸測試，仍維持空白回應 fail closed。
- 瀏覽器 review 發現「公司管理／擁有者」可進入資料健檢，但 API 原只接受 platform superuser；已改為與 `system_ops` 導覽一致的 owner／admin 權限並更新 route contract test，不以平台密碼繞過產品缺陷。
- 公開 Demo 的 middleware 會正確阻擋外部整合 POST；UI 已同步停用實測按鈕並說明正式租戶才可執行，避免出現看似可按、實際必然 403 的假操作。

## 誠信邊界

本 Code Review 證明程式與設定閘門正確，不等於八策真實資料已驗收。正式部署後仍必須：

1. 在正式容器執行七項 live probe 全數通過。
2. 以八策代表性文件、圖片、音檔與影片完成端到端 Input → review → publish → retrieval → citation 驗收。
3. 建立具名使用者與專屬租戶資料邊界後，才能宣稱第一租戶已正式啟用。
