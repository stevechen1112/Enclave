# Input I3 Core Capture 平台化 — Code Review

日期：2026-08-29
結論：**INTERNAL SOFTWARE PASS；實體裝置 review gate 尚未完成，因此暫不開放 Input I4。**

## 已完成範圍

- Capture API 已從 MKA pack composition 提升為核心 `/api/v1/knowledge/captures`；舊 `/api/v1/knowledge-captures` 僅作隱藏相容 alias。
- MKA 關閉時 core capture route、policy、chunk、complete 與 canonical asset 仍存在；MKA 的 `LongInterviewRecorder` 只保留 presentation adapter。
- `CoreAudioRecorder`、capture API client 與 IndexedDB chunk queue 已移到 `frontend/src/platform/input`，不依賴 `components/mka` 或 `services/mka`。
- `/knowledge/new` 新增「現場擷取」：長錄音直接建立 canonical audio asset；照片與影片進入既有 I2 resumable upload。
- 錄音前明示 consent；錄製中顯示錄製時間、安全上傳時間、租戶上限、裝置可用空間估計、保留天數與術語筆數。
- page hidden／切 App 時先要求 MediaRecorder flush；網路恢復時自動嘗試 drain；IndexedDB 寫入失敗會停止錄音並保留明確錯誤。
- 租戶管理者可經 core policy API 設定 capture 時間上限及音訊／逐字稿保留政策；session 建立時保存不可變政策與術語 SHA-256 快照。
- classification、department ACL、廠區／產線／設備／工單等 allowlisted context 會投影到 canonical SourceAsset。

## Review 中發現並修正

1. 舊 capture router 由 MKA pack 掛載，關閉 pack 後無法錄音；現已由 core API 永久掛載。
2. 舊前端錄音元件與 queue 由 MKA 擁有；現已移至平台 Input，MKA 僅依賴 public adapter。
3. 舊 capture asset 固定為 confidential/private 且 `source_system=mka_capture`；現依核心 intake governance 建立 `core_capture` asset，department 使用 restricted ACL，並標記 direct intake。
4. 轉寫完成原會覆蓋 `transcript_metadata`，導致 capture governance 遺失；現改為合併更新。
5. 時間上限原為部署全域常數；現新增 tenant policy 欄位與 `input_i3_capture_policy_001` migration，並在 session snapshot、chunk 與 complete 三處執行上限。
6. production build 發現舊 capability fixture 缺少 I3 欄位；已補齊並重新 build 通過。

## 驗證結果

- Backend I3／pack boundary／canonical asset／retention／capability：46 passed。
- Frontend full Vitest：34 files、118 passed（最終數字以最後回歸為準）。
- TypeScript、ESLint、Ruff（保留既有 FastAPI／legacy 例外）與 Vite production build：PASS。
- Playwright：Desktop Chrome、Pixel 7 Chromium emulation、iPhone 15 Chromium emulation、Galaxy Tab S9 Chromium emulation，共 4 passed。
- Alembic：fresh upgrade 至 `input_i3_capture_policy_001`、downgrade 至 I2、re-upgrade 與 current head 全部 PASS。
- `git diff --check`：PASS。

## 尚未通過的外部 gate

- iPhone 實機 Mobile Safari。
- Android 實機 Chrome。
- 真實鎖屏、切 App、來電、Wi-Fi／行動網路切換與裝置空間不足。
- 每次實機錄製的媒體樣本 hash、session id 與 asset id 證據。

詳細執行矩陣見 `reports/INPUT_I3_DEVICE_VALIDATION_MATRIX_2026-08-29.md`。上述項目需要實體裝置與可登入測試環境；桌面模擬不構成替代證據。未執行生產 migration，也未部署本階段變更。
