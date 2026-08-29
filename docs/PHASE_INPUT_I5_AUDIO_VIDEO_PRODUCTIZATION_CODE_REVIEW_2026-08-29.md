# Input I5 音訊與影片產品化 — Code Review

日期：2026-08-29
結論：**INTERNAL ENGINEERING PASS；外部媒體認證仍待完成；准入 Input I6。**

## Review 基線

- Commit：`d85b1503e1058ec4865d3f21a4477a363205c351` 加目前未提交工作樹。
- Schema revision：`input_i5_media_product_001`。
- Input registry SHA-256：`ef69b33db9596fa5842754665184d4f50fd9c4a9e0e17dff11eee18b68b2a583`。
- OpenAPI route contract SHA-256：`8729278258ac75f02d14c1182189406622e0f90e4e30118ca801b9e002d23a34`（296 routes）。
- Codec corpus：`artifacts/input/i5_corpus/manifest.json`；所有檔案有 SHA-256，來源為內部 synthetic signal，不含客戶資料。
- 實測報告：`artifacts/input/i5_media_report.json`。

## 已完成範圍

- 長音訊不再整檔載入記憶體；worker 先由 tenant object storage 下載到暫存檔，ffprobe 驗證後切成有上限的 300 秒片段，逐段 ASR、建立 audio time span、寫入 checkpoint 與 partial-readiness event。重試沿用已安全保存的原檔，使用者不需重傳。
- 重複文字的 artifact identity 納入 start/end/speaker，避免長錄音不同時間說出相同句子時被錯誤合併。
- 音訊產生 MP3 瀏覽器預覽；影片產生 H.264/AAC、yuv420p、fast-start MP4 proxy。兩者都使用 tenant-prefixed object key、短效 resource-bound token 與 canonical asset ACL。
- 影片在 proxy 前重新 probe 並比對 upload-time metadata；之後依 probe、demux、transcript partial、keyframe、OCR partial、timeline、governance 更新進度。
- Input capability contract 正式揭露 resumable upload、background progress、partial readiness、browser proxy、音／影片 codec 與音訊時長上限。
- 動作、設備狀態、異音、逐字稿、OCR、timeline 與 procedure 均維持 candidate/review-required；低信心或未解 SOP conflict 不能自行發布。
- 覆核 UI 優先播放 proxy，可由逐字稿、畫面、OCR、跨模態候選與程序步驟跳至 exact timestamp；音訊資產頁可播放受控 proxy 並查看逐段進度。
- 實際 ffmpeg/ffprobe corpus 驗證 MP3/WAV/M4A/OGG/FLAC 與 MP4/MOV/WEBM/MKV；duration boundary mean absolute error 3.06 ms、max 24 ms，內部門檻 100 ms。

## Code Review 發現並修正

1. 首版 Alembic revision ID 超過 `alembic_version.version_num varchar(32)`，真實 PostgreSQL fresh upgrade 失敗。已縮短為 `input_i5_media_product_001`，並完成 upgrade → downgrade I4 → re-upgrade。
2. 首版影片 worker 在重新 probe／比對 upload metadata 前建立 proxy，對遭替換或異常來源可能先消耗大量轉碼資源。現先 fail-closed re-probe，再允許 proxy 與後續分析。
3. 舊長音訊 worker 透過 `get_bytes()` 將完整來源載入記憶體並一次送往 ASR，不符合長檔邊界。現改為 `get_to_file()`、bounded chunk、逐段 commit。
4. 舊 transcript hash 只含文字，相同句子在不同時間會 collapse。現 identity 包含文字、時間與 speaker。
5. 音訊原無通用預覽，影片原檔也不一定能在瀏覽器解碼。現新增同一 `media_proxy` artifact 與受控 artifact media route，保留舊 video-artifact route 相容性。

## 驗證結果

- I0–I5、orchestrator、asset、video、storage related backend：123 passed。
- I5 + existing video focused regression：48 passed；audio preview/API combined regression：56 passed。
- Frontend full Vitest：34 files、119 passed。
- TypeScript、ESLint、Vite production build：PASS。
- Ruff（I5 相關 Python）：PASS；compileall：PASS；`git diff --check`：PASS（僅 Windows line-ending 提示）。
- Alembic isolated PostgreSQL/pgvector fresh DB：upgrade head → downgrade I4 → re-upgrade I5，PASS；暫存容器已移除。
- 實際 codec matrix：audio 5/5、video 4/4 PASS；timeline duration alignment PASS。

## Review gate 對照

- Architecture：長媒體能力位於 core Input；Domain Pack 無反向依賴；migration 可回滾。PASS。
- Tenancy/security/privacy：原檔、proxy、keyframe 皆 tenant-keyed；媒體 URL 綁 tenant/user/resource，取用時重查 active user 與 asset ACL；候選不自動發布。PASS。
- Reliability：bounded memory/chunks、逐段 checkpoint、idempotent identity、原檔保留與 retry no-reupload。PASS。
- UX/accessibility：背景階段、百分比、partial wording、audio/video preview 與 exact-time seek 可用。PASS。
- Quality/evidence：實際 container/codec corpus、timeline error、candidate semantics、SOP conflict 與人員覆核證據鏈。INTERNAL PASS。
- Performance/cost：chunk/keyframe/proxy 皆有上限，但 live 24h queue/provider/storage campaign 未執行。DEFERRED TO I7 LIVE GATE。
- Compatibility：舊 video artifact URL 保留；新 generic artifact URL 為 additive；I2 upload session 不變。PASS。
- Documentation/claims：報告明示 synthetic codec 證據不等於實機、口音或工廠 ASR 認證。PASS。

## 未解風險與工程續行邊界

- `device_origin` 與 `speech_quality` 為 PENDING：尚未提供實體 iPhone／Android、多人、台灣口音、機台噪音下人聲及合法 ground truth。
- 24 小時 live queue/degradation 為 NOT RUN；不得據此宣稱 24/7 SLA 或商用容量，I7 review gate 不接受以 unit/synthetic test 取代。
- 跨產業 action/equipment/anomaly accuracy 未證明，相關輸出只能是候選。
- 未執行 production migration，未部署。

依使用者要求，外部／實機缺口只豁免後續工程階段的前置，不豁免商用認證。I5 內部工程 gate 通過，可開始 I6。
