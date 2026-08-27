# Phase F1 Code Review：基礎影音管線與證據覆核

**Review date**: 2026-08-26
**Gate result**: PASS（完成下列修正後）

## Review 範圍

- 影片上傳、排毒、SHA-256、probe 與容量/編碼/時長限制。
- `SourceAsset → AssetRevision → DerivedArtifact → EvidenceSpan` 追溯鏈。
- demux、帶時間碼 ASR、關鍵幀、OCR 與審核候選。
- Celery 重試/冪等、租戶 RLS、物件鍵邊界與短效媒體權杖。
- 逐字稿/畫面/步驟時間軸 UI、人工核准後的核心檢索發布。

## 發現與修正

1. **[High] HTML media 無法夾帶 API Authorization header**
   - 修正：加入 15 分鐘、租戶與單一資源綁定的簽章 JWT；影片與關鍵幀內容端點只接受相符的權杖。
2. **[High] 可能用跨租戶 review decision 連到別人 artifact**
   - 修正：review decision 使用 `(tenant_id, artifact_id, asset_revision_id)` 複合外鍵，並有跨租戶負向測試。
3. **[Medium] 播放器回應的 Content-Disposition 可能變成下載**
   - 修正：local backend 明確使用 `inline` 與正確 media type；remote backend 無 object key 時 fail closed。
4. **[Medium] 工作端與上傳端 probe 結果可能不同**
   - 修正：worker 重新 probe，codec 或時長偏差超限即拒絕。
5. **[Medium] 重試可能重複產生 artifact/keyframe**
   - 修正：keyframe object id 來自 revision + timestamp 的 deterministic UUID；artifact 以 provider/version/content hash 冪等建立。
6. **[Low] 新增 core provider 使舊的 composition 斷言過期**
   - 修正：回歸測試明確斷言 `core.video_procedure` 與可選 pack provider 的組合。

## 驗證證據

- Backend F1 專屬測試：9 passed。
- Asset/Ingestion/Knowledge 相關回歸：修正舊斷言後 50 passed。
- Frontend：69 passed；production build 與 ESLint 通過。
- PostgreSQL：全新 schema `upgrade head`、F1 downgrade/upgrade 往返、`alembic check` 通過。

## 限制與下階段入口

F1 只對基礎影音管線封板。說話者分離、鏡頭邊界、動作/設備/異常聲音候選屬 F2；規則/風險/例外與 SOP 衝突治理屬 F3。兩者未通過各自 code review 前，Phase F 不會標記完成。
