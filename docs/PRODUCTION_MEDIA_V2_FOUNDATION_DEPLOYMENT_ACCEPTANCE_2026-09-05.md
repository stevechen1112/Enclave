# Media v2 基礎正式環境發布與驗收紀錄

日期：2026-09-05（台灣時間）  
狀態：**基礎程式與資料結構已部署；所有新媒體能力旗標保持關閉**

## 1. 結論

音訊與影片多模態知識管線 AV0–AV8 的基礎程式、資料模型與 migration 已發布至 `https://kachu.tw`。正式環境健康、資料庫可用、前後端版本身分一致，且登入後 canonical route smoke 已通過。

本次發布刻意不對任何租戶啟用新版媒體處理。它證明的是「可安全部署、可追溯、可回復、預設不改變既有租戶行為」，不是宣稱音訊／影片泛化品質或第一租戶試用已完成驗收。下一階段仍須依計畫執行 shadow、受控租戶 canary 與真實素材品質驗收。

## 2. 已部署版本

| 項目 | 值 |
|---|---|
| 產品來源 commit | `e2cc7490217c689343d6cc8aec7890288d31d8f2` |
| 版本標籤 | `release-20260905-media-v2-foundation-v2` |
| Release ID | `rc-33907977487-1` |
| Deployment manifest | `dm-1ff08257be3d698ee5153a66` |
| Schema head | `av_media_v2_001` |
| Source dirty | `false` |
| 部署檔案數 | 720 |
| 正式部署工作流程 commit | `98571d00db7425db0b759f33c4d3bde4c7832b0c` |

不可變映像 digest：

- backend：`sha256:810c81b51a585da6ba76a2f2ed1ccd568fe40929cd7b1ad6f05bf34344dd3931`
- frontend：`sha256:e8d25b7ea8940de8421ebad36c0f01689559a99200bd52fabbbe8bf98e13d73a`
- gateway：`sha256:a168c8456ae30ae9caf9dbcb26a239a81a3d1b1795820991c29e85cf726dfea7`

## 3. 正式環境功能旗標

2026-09-05 於正式 Web 容器直接讀取應用設定的結果：

| 旗標 | 正式值 |
|---|---:|
| `MEDIA_PIPELINE_V2` | `false` |
| `MEDIA_V2_TENANT_ALLOWLIST` | 空白 |
| `AUDIO_PRECISION_PASS_V1` | `false` |
| `VIDEO_ADAPTIVE_SAMPLING_V1` | `false` |
| `MULTIMODAL_SEGMENT_V1` | `false` |
| `ENTITY_LINKING_V1` | `false` |

因此目前沒有租戶被導向新管線；即使誤開個別子功能，總開關與空 allowlist 仍會 fail closed。

## 4. 建置與發布證據

### 4.1 程式與 release pipeline code review

- 媒體基礎 commit 的針對性驗證：45 項新測試 + 123 項既有回歸，共 168 項通過。
- release identity 與 Demo reconciliation：12 項測試通過；fresh pgvector migration 至 `av_media_v2_001` 通過。
- 發布流程 PR #3：CI run `33907275457` 全綠；包含 Backend Tests、Backend Lint、Client Frontend Build、Dependency Audit、Playwright E2E、Docker Build Check。
- HTTPS smoke 修正 PR #4：CI run `33909037505` 全綠；同樣六類檢查全部通過。
- 本機新增部署架構回歸檢查：39 項通過；workflow YAML parse 與 `git diff --check` 通過。

連結：

- PR #3：<https://github.com/stevechen1112/Enclave/pull/3>
- PR #4：<https://github.com/stevechen1112/Enclave/pull/4>
- 最終 HTTPS smoke CI：<https://github.com/stevechen1112/Enclave/actions/runs/33909037505>

### 4.2 不可變映像與 provenance

Build Release Candidate run `33907977487` 成功，完成：

1. 精確 checkout 已標記的來源 commit。
2. 工作區乾淨與 release source gate。
3. backend、frontend、gateway 映像建置及推送。
4. SBOM、映像 digest、deployment manifest 綁定。
5. 來源 commit 身分 fail-closed 比對。

Release source gate 結果：`PASS`；dirty file 0、secret finding 0、errors 0。

- Build run：<https://github.com/stevechen1112/Enclave/actions/runs/33907977487>
- 本機 provenance：`artifacts/media_v2/release_provenance_e2cc749/`

### 4.3 正式部署

最終 Deploy Production run `33909780859` 成功，依序完成：

1. 正式 PostgreSQL 備份。
2. 拉取精確版本映像。
3. 暫停 Web、worker、worker-beat。
4. 專用 `migrate` service 執行 migration。
5. DB role provision、superuser initialization、Demo reconciliation。
6. 服務啟動及健康檢查。
7. 公開 HTTPS edge smoke。
8. backend／frontend／schema release parity。
9. 登入後 canonical routes smoke：3 項通過。

- Deploy run：<https://github.com/stevechen1112/Enclave/actions/runs/33909780859>
- 最新備份：`/opt/enclave/backups/enclave_20260904_191044.sql.gz`
- 備份 gzip integrity：`PASS`

## 5. 正式環境最終複核

| 驗證 | 結果 |
|---|---|
| `https://kachu.tw/` | HTTP 200 |
| `https://kachu.tw/health` | `status=ok`、database `ready` |
| `https://kachu.tw/release.json` | 與 backend release metadata 一致 |
| 來源 commit | 精確為 `e2cc749...` |
| Schema | `av_media_v2_001 (head)` |
| Web / worker / frontend / gateway / db / redis | running；有 healthcheck 者皆 healthy |
| Canonical routes | `/overview`、`/ask`、`/knowledge/assets`、`/knowledge/new`、`/knowledge/review`、`/knowledge/quality`、`/system/health`、`/job` 均存在 |
| 登入後 browser smoke | 3 passed |
| 新媒體旗標 | 全部關閉；allowlist 空白 |

## 6. 本次發布過程發現並永久修正的缺陷

### 6.1 GitHub production environment 未配置連線資訊

首次正式工作流程在備份前即 fail closed，沒有改動 production。已補齊 production environment 所需 host、user、SSH key 與 public base URL；未將密鑰寫入 repository。

### 6.2 備份方式依賴主機上的 `pg_dump`

主機沒有直接安裝 `pg_dump`，舊流程無法備份。已改用 containerized DB-only backup，並實際產生及驗證 gzip 備份。

### 6.3 部署流程未載入分離後的正式環境檔

正式環境使用 `.env.production`、`.env.db-admin`、`.env.maintenance` 三份檔案。舊 workflow 只載入單一檔，Compose 在停止服務前 fail closed。已統一載入 canonical env files，並以 regression test 鎖定。

### 6.4 Demo tenant 留有已退役模組綁定

嚴格初始化檢查發現 synthetic Demo tenant 尚有 `spec_sop` 舊綁定。只清理明確標記為 Demo／非真實公司的 tenant，未動真實租戶。產品程式已改為每次 seed 自動 reconciliation：建立 canonical bindings 並移除 retired synthetic Demo bindings。

### 6.5 映像來源 commit 被 workflow commit 汙染

建置器最初嘗試覆寫 GitHub 保留的 `GITHUB_SHA`，映像 metadata 因而顯示 workflow commit，而非實際 packaged source。已新增 `ENCLAVE_SOURCE_COMMIT` 並在建置前 fail closed 比對。正式環境現在正確顯示 `e2cc749...`。

### 6.6 HTTP localhost 首頁被安全轉址誤判為失敗

正式 gateway 正確將 HTTP 轉為 HTTPS，舊 smoke 卻要求 `http://localhost/` 必須直接回 200。已改成驗證實際使用者會到達的公開 HTTPS URL，並讓 smoke 階段同樣載入 canonical env files。

### 6.7 三組架構測試重複硬編碼舊 migration 指令

production 已提升為專用 migration service，三組既有測試仍搜尋舊的 raw Alembic 字串。已完整掃描同類測試，分別驗證 production 與 staging 的真實 migration contract，沒有為了過測試退回較弱的部署方式。

## 7. 回復與安全邊界

- 資料庫變更已在 migration 測試中驗證可升級／降級；正式環境部署前已有完整 DB backup。
- 映像以 commit tag 與 digest 綁定，可回到前一個明確映像版本。
- 新功能目前全部關閉；若下一階段 shadow 發生問題，可移除 tenant allowlist 或關閉總開關，不需回滾 schema。
- `release-20260905-media-v2-foundation-v1` 保留作為被取代的歷史候選，不移動既有 tag；正式採用 v2。

## 8. 尚未完成與下一個核准門檻

本次沒有宣稱以下事項完成：

- 未對八策股份有限公司或任何真實租戶啟用 media v2。
- 未以真實音檔／影片完成 shadow 結果品質比較。
- 未完成術語、人名、金額、時間碼、OCR、畫面事件、跨模態對齊與 entity linking 的正式品質門檻。
- 未完成長檔成本、處理時間、重試／恢復與人工覆核負荷的 tenant canary 驗收。

建議下一步依序執行：

1. 在隔離的測試租戶啟用 `MEDIA_PIPELINE_V2` shadow，只寫新衍生資料、不影響既有檢索回答。
2. 使用既定音訊／影片 corpus 比較 legacy 與 v2，輸出逐檔品質、延遲、成本與錯誤分類。
3. shadow gate 通過後，才將第一個受控 tenant UUID 加入 allowlist。
4. 先開總管線，再依證據逐一開 audio precision、adaptive sampling、multimodal segment、entity linking；每一步都保留 rollback gate。

只有上述 canary 與真實素材驗收通過後，才能把「媒體基礎已安全部署」提升為「可交付第一租戶正式使用」。
