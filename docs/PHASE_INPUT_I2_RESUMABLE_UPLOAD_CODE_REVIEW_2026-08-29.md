# Input I2 通用續傳與弱網可靠性 — Code Review

日期：2026-08-29
結論：**PASS；可開放 Input I3，不代表已部署至生產環境。**

## Review 範圍

- 平台 API：`/knowledge/upload-sessions` init、status/resume、part、commit、abort。
- 持久化：`upload_sessions`、`upload_parts`、tenant composite FK、owner boundary、idempotency unique key、RLS。
- 儲存：`StorageBackend` local 與 S3-compatible multipart create/upload/complete/abort。
- Canonical 邊界：transport commit 後呼叫既有 knowledge asset intake；Document、Audio、Video 的 scan、quota、ACL、revision 與 ingestion job 邏輯不分叉。
- Web UX：三路並行、SHA-256、有限重試與退避、暫停、IndexedDB session 恢復、重新登入續傳、明示進度與錯誤。
- 維護：過期 session 的跨租戶 maintenance task 與 staging cleanup。

## 架構判定

I2 維持原定產品方向：多租戶是安全邊界，Input 是共用平台能力，知識資產是唯一內容權威，MKA 等場景模組不持有一般檔案 transport。完成 multipart 只產生暫存物件；只有 canonical intake 成功後，session 才標記 committed 並清除 staging。若 canonical intake 已成功但回寫 session 前中斷，相同 idempotency key 會沿用既有資產，不會建立重複資產。

## Review 中發現並修正

1. 初版把 JSON context 直接送入既有字串 validator，整合測試抓到 500；已改為序列化後進入同一 allowlist／大小驗證。
2. 初版只以 `staging_completed` 判斷清理；若 provider complete 與 DB commit 之間故障，可能留下 staging object。現改以 storage `exists` 為權威：存在即 delete，否則 abort multipart。
3. 初版沿用 client MIME；現改為 server-owned format registry 的 media type，避免相同副檔名因瀏覽器 MIME 差異破壞 idempotency identity。
4. concurrent init 可能同時建立 provider upload；DB unique race 現會 abort loser，回傳相同 identity 的 winner，衝突 identity 回 409。
5. 過期清理原未涵蓋 `committing`；現已納入，避免 process crash 造成永久卡住。
6. 前端原會重試所有 4xx；現只重試 network、408、429、5xx，checksum／權限等確定性錯誤立即回報。

## 安全與一致性結果

- Session 查詢與所有 mutation 同時綁定 `tenant_id + owner_id + session_id`；同租戶其他管理員與其他租戶皆回 404。
- 每個 part 必須符合 part number、精確 byte length 與 client/server SHA-256；已確認 part 重送不增加計數，不同內容重送回 409。
- Commit 要求 part number 完整連續且總 bytes 相符，materialize 後再次計算整檔 SHA-256；可選 expected final hash 不符回 422。
- local 與 S3-compatible key 均受 tenant-prefix validator 約束；S3 使用原生 multipart API，非單一 API 節點的本機 chunk 狀態。
- Session 過期、明確 abort、commit success 都有對應 provider staging cleanup。

## 驗證證據

- Backend 最終整合回歸：60 passed（含 upload session API、large-file／expiry／property、capability snapshot、storage、context 與 canonical knowledge asset）。
- Frontend full Vitest：33 files、115 passed（含 transient retry helper 5 passed）。
- TypeScript、ESLint、Vite production build：PASS。
- Chromium E2E：401 清除登入後，IndexedDB 還原同一 session；part 1 實際只傳一次，重新登入只補 part 2，PASS。
- Alembic fresh database：完整 upgrade 至 `input_i2_resumable_upload_001`；單階段 downgrade、re-upgrade 與 current head 均 PASS。
- Storage contract：local out-of-order/abort、mock S3 create/upload/complete/abort、12 組固定 seed 隨機 arrival order 均 PASS。

## 不阻擋 I2 的外部驗證項目

- 真實客戶 S3、R2 或 MinIO endpoint 的憑證、CORS、timeout 與 provider-specific error 行為。
- 工廠 Wi-Fi／4G 切換、瀏覽器背景節流、低儲存空間與實體手機鎖屏。
- 多 API replica 的長時間 soak 與峰值頻寬容量數據。

上述需要部署環境或實體裝置，不應偽稱已完成；它們屬 rollout certification，而非尚缺的 I2 程式碼邊界。未執行生產 migration，也未部署本階段變更。
