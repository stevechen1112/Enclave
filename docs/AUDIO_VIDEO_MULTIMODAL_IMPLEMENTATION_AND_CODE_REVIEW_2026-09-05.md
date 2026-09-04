# Enclave 音訊／影片多模態工程實作與 Code Review 報告

> 日期：2026-09-05
> 對照計畫：`AUDIO_VIDEO_MULTIMODAL_KNOWLEDGE_ENGINEERING_PLAN_2026-09-05.md` v1.1
> 審查範圍：AV0–AV8 軟體交付、資料庫 migration、權限邊界、回歸測試、前端建置與外部驗收缺口
> 結論：**軟體主幹與認證工具已實作；真實 corpus、實機、24/72 小時運轉及租戶簽認尚不能由工程端代替，故不得宣稱 `PILOT_CERTIFIED`。**

---

## 1. 實作前複查結論

計畫的核心方向維持不變：原始媒體與版本是唯一來源身分；ASR、OCR、畫格、片段摘要與 entity link 都是可追溯衍生物；只有經 Knowledge Authority 發布至 active release 的內容才能進正式 Ask。

本次複查特別確認三個邊界：

1. `media_analysis_runs` 是作業、成本、品質與失敗紀錄，不是第二套知識權威。
2. 新媒體功能一律以 feature flag shadow-first 上線，關閉時不得改變 V1 行為。
3. 「程式完成」與「真實品質認證」分開；後者必須使用未洩漏 ground truth、真實裝置與 tenant truth owner 簽認。

實作前複查文件見 `AUDIO_VIDEO_MULTIMODAL_PREIMPLEMENTATION_REVIEW_2026-09-05.md`。

---

## 2. AV0–AV8 實作對照

| Phase | 軟體交付 | Code Review | 尚待外部證據 |
|---|---|---|---|
| AV0 Truth Contract | 嚴格 corpus classification、不可變 hash 綁定、CER/WER、critical terms、event IoU、speaker turn、OCR bbox、entity、retrieval、禁詞插入、重複候選與 tenant leak 評測 | PASS | 真實 V1/V2 baseline、sealed holdout、tenant truth owner 標註 |
| AV1 Contract | analysis run、artifact derivation、asset/unit entity links、entity relationship、composite tenant FK、RLS、downgrade | PASS | 正式環境 production-sized migration rehearsal |
| AV2 Audio | 品質剖面、16 kHz PCM working copy、自適應重疊切段、Pass A diarization、Pass B context/glossary candidate、critical token、raw/correction 分離 | PASS WITH EXTERNAL FOLLOW-UP | 每個真實 audio slice 的 CER、critical omission/hallucination 與成本結果 |
| AV3 Video | 0.2–4 FPS bounded scan、dHash 去重、清晰度／亮度／變化評分、自適應選幀、OCR track | PASS WITH EXTERNAL FOLLOW-UP | 快速動作 coverage、OCR bbox/track 與長片成本 corpus |
| AV4 Segment | provider contract、canonical time segment、schema-constrained candidates、exact evidence gate、ASR/OCR 數值矛盾、安全降級 | PASS WITH EXTERNAL FOLLOW-UP | 供應商與模型須由 corpus 決定；高成本 VLM adapter 尚未在無基線時預設啟用 |
| AV5 Entity Retrieval | approved alias、歧義不自動核准、asset/unit projection、單跳關聯、active release/ACL 重新准入、撤權失效 | PASS WITH EXTERNAL FOLLOW-UP | 「設備 A」跨 SOP、手冊、影片、音訊、圖片與維修紀錄的 tenant corpus |
| AV6 Review/Publish | 音訊 raw/correction、影片 OCR track/segment UI、證據時間跳轉、結構性 artifact 不淹沒一般待辦、人工核准後發布 | PASS WITH EXTERNAL FOLLOW-UP | 兩人租戶與手機／平板的實際任務完成時間及高風險雙人流程 |
| AV7 Reliability | 冪等 run、單調 checkpoint、成本預估與上限、optional pass circuit breaker、故障 campaign evaluator、partial/degraded/failed truth | PASS WITH RUNTIME FOLLOW-UP | 24 小時 queue campaign、72 小時 soak、真實 429/5xx/worker crash/object-store 故障注入 |
| AV8 Certification | fail-closed certification builder、實機矩陣、完整旅程、60+60 corpus、20% sealed、三方簽認硬門檻 | TOOLING PASS | iPhone Safari、Android Chrome、弱網、真實工廠 corpus 與三方簽認 |

`PASS WITH EXTERNAL FOLLOW-UP` 表示該 Phase 的工程路徑與安全邊界已具備，不表示內容準確率已通過商用品質門檻。

---

## 3. 主要程式交付

### 3.1 資料與治理

- `app/models/media_analysis.py`：新增分析執行、artifact lineage、資產／Knowledge Unit entity projection 及 entity relationship。
- `app/db/migrations/versions/av_media_v2_001.py`：新增表、索引、composite tenant FK、RLS policy、artifact vocabulary 與完整 downgrade。
- `app/services/media_analysis_runs.py`：穩定 run key、有限狀態轉換、冪等 derivation edge。
- `app/services/entity_knowledge_links.py`：明確 metadata 投影、approved alias、歧義候選、撤權與 bounded one-hop expansion。

### 3.2 音訊

- `app/services/audio_precision.py`：品質剖面、lossless working audio、重疊切段、critical token、術語校正與 overlap merge。
- `app/services/voice_gateway.py`：Pass B context/glossary transcription；沒有時間碼時只保留 correction candidate，不覆寫 Pass A。
- `app/tasks/audio_tasks.py`：analysis run、成本 Gate、working copy 持久化、raw/correction lineage、斷路器、checkpoint 與 review routing。

### 3.3 影片與多模態

- `app/services/video_adaptive_sampling.py`：自適應 FPS、候選上限、perceptual dedupe、frame scoring、OCR track。
- `app/services/video_processing.py`：feature-flagged adaptive sampling、media probe、OCR track projection。
- `app/platform/multimodal.py`、`app/services/segment_understanding.py`：片段輸入／輸出 contract、候選型別、證據完整性與安全降級。
- `app/tasks/video_tasks.py`：成本、entity、segment、analysis run 與 terminal quality metrics 串接。

### 3.4 Ask、審核與前端

- `app/services/retrieval_facade.py`：entity alias query 與單跳擴張，但每筆結果仍須重新通過 active release、ACL 與 applicability。
- `app/services/typed_knowledge_projection.py`、`app/services/knowledge_authority.py`：發布時寫入 Knowledge Unit entity projection。
- `app/services/review_workspace.py`：系統結構產物不進一般待辦；correction 核准只發布候選文字，不發布內部 JSON。
- `app/services/media_review_snapshot.py`：tenant-scoped review read model；rolling deployment 未有新表時安全降級。
- `frontend/src/pages/knowledge/AssetDetailPage.tsx`、`VideoReviewPage.tsx`：顯示品質、raw/correction、OCR track、片段候選、時間跳轉與「尚未發布」。

### 3.5 可靠性與認證

- `app/services/media_reliability.py`：成本、checkpoint、provider circuit breaker、故障 campaign 判定。
- `app/services/media_feature_flags.py`：總開關與明確 tenant UUID allowlist 雙重准入；空白或無效名單 fail closed，capability 不可繞過租戶灰度邊界。
- `app/eval/media_quality_v2.py`：可重放的多層品質 evaluator。
- `app/services/media_certification.py`、`scripts/run_media_v2_certification.py`：不可用模擬資料冒充實機／租戶認證的 fail-closed Gate。
- `testdata/media_quality_v2/*`：manifest 與 external evidence 範本；範本明確不屬於真實 accuracy evidence。

---

## 4. Code Review 發現與修復

本輪不是只看測試綠燈；逐項對照 call graph、資料 authority、flag、migration 與 failure path。已修正：

1. **RLS session key 不一致**：migration 原先使用錯誤 tenant setting；已統一為 `app.tenant_id`，並保留受稽核的 `app.bypass_rls`。
2. **lineage 只有 JSON、沒有正規化 edge**：Pass A → correction 及 evidence → segment summary 現在會寫入 `artifact_derivation_links`。
3. **metadata 沒有真正連到 entity**：明確設備／產品／客戶等 metadata 現在會經 canonical name／approved alias 解析；歧義只建立 candidate，不進 retrieval。
4. **發布後 entity projection 未接上**：Knowledge Authority 現在於 feature flag 開啟時把 applicability 投影至 unit revision。
5. **撤權未明確傳播至 asset entity links**：資產 tombstone 時會撤銷所有 revision 的有效／候選 entity links。
6. **音訊只有影片有成本預估**：audio 現在同樣在外部呼叫前執行 per-asset 成本 Gate。
7. **斷路器只有 class、未接 provider call**：precision STT 已接共用 provider breaker；Pass B 故障會降級，不丟棄 Pass A。
8. **OpenAI prompt 傳 `None` 的相容風險**：沒有 context 時直接省略欄位。
9. **WAV 仍宣告成 MPEG**：精準管線送 Pass A 時改用正確 MIME；magic-byte sniff 仍作第二層防護。
10. **correction JSON 可能被當正文發布**：核准時只發布 `candidate` 文字；空／錯誤 payload fail closed。
11. **feature flag 關閉仍查新表**：回歸測試實際抓到 tombstone path 的問題；已隔離並重跑通過。
12. **評測 Gate 使用平均值掩蓋 slice**：改以 median CER/OCR CER 執行門檻，同時保留 mean 作診斷。
13. **全域詞頻被誤當重複幻覺**：改成逐案例連續 1–3 gram 重複候選，不再把正常高頻詞誤報。
14. **認證未綁定乾淨 release**：AV8 software evidence 現在要求 clean working tree 與 64 字元 release manifest hash。
15. **明確 entity UUID 被誤當名稱**：resolver 現在先以 tenant/type-scoped UUID 查找，再走 canonical name／approved alias；跨租戶 UUID 仍解析不到。
16. **媒體 v2 原為全域開關，不符合逐租戶 shadow**：新增 `MEDIA_V2_TENANT_ALLOWLIST`；總開關、租戶 UUID 與個別 capability 三者必須同時成立。租戶退出灰度後，刪除資產仍會清理先前建立的 entity projection；舊 schema/相容測試資料庫沒有新表時安全回傳 0，不回滾既有交易。

Review 後未發現會讓未覆核 media candidate 自動進 active Ask 的新路徑。

---

## 5. 驗證證據

### 5.1 Python 與回歸

- 新增 AV0–AV8 單元／契約測試：45/45 通過（含 4 項租戶灰度 fail-closed 測試）。
- 既有媒體、Knowledge Asset、Review Workspace、Knowledge Authority、Ask KQ4、RetrievalFacade、worker isolation 與 multimodal quality 回歸：初跑發現 2 項 flag 隔離缺陷；修復後完整重跑 123/123 通過。
- `compileall`：通過。
- `ruff`（本次影響檔案）：通過。

### 5.2 PostgreSQL migration

在一次性 `pgvector/pgvector:pg16` 執行：

1. 空資料庫 `upgrade head`：PASS。
2. `downgrade input_i10_confidence_001`：PASS。
3. 再次 `upgrade head`：PASS。
4. 五張新表均為 `rowsecurity=true`，五個 `tenant_isolation` policy 均存在。
5. 非 superuser、`NOBYPASSRLS` app role：tenant 1 只看見 tenant 1 的一筆；切到 tenant 2 只看見 tenant 2 的一筆。
6. tenant 1 session 嘗試寫入 tenant 2 關聯：被 PostgreSQL RLS 拒絕。

一次性測試 container 已停止並自動移除。

### 5.3 Frontend

- TypeScript `tsc --noEmit`：PASS。
- Vite production build：PASS，3,259 modules transformed。

### 5.4 未列為 PASS 的證據

- 此工作目錄原本即有其他未提交變更，因此目前不是可認證的 clean release。
- 未在本輪重新跑完整 1,801 項 suite；先前嘗試受到本機預設 PostgreSQL `localhost:5435` 未提供服務及既有 fixture 假設影響。此次改以受影響範圍回歸及一次性 PostgreSQL migration/RLS 驗證，不把環境錯誤寫成產品 PASS。
- 未執行 24 小時 queue campaign、72 小時 soak、真實 provider 大量成本測試。
- 未取得 60 支真實音訊、60 支真實影片、20% sealed holdout 與三方簽認。
- Fail-closed runner 的本輪結果已寫入 `artifacts/media_v2/certification_2026-09-05_final_review.json`，正確回報 `NOT_READY`；阻擋項為非 clean release 與全部外部證據尚未提供。

---

## 6. 遺漏檢核

本次逐項檢查計畫第 5–22 節，結果分為三類：

### 6.1 已在程式中落地

- 原檔／revision 不可變、衍生物不覆寫來源。
- raw、correction、human-reviewed publication 分離。
- 共用毫秒時間軸與 exact EvidenceSpan。
- bounded adaptive scan、frame dedupe、OCR track。
- schema-constrained segment candidates 與 unsupported high-risk fail closed。
- tenant-scoped entity、approved alias、ambiguity routing、bounded one-hop。
- active Knowledge Unit release、ACL、撤權與 authority 重新准入。
- feature flags、成本上限、checkpoint、provider degradation、認證 runner。

### 6.2 有意不在缺乏 corpus 時寫死

- 實際 ASR／VLM／OCR 供應商與模型。
- 音訊濾波、VAD、precision routing、FPS 與 frame score 的正式生產門檻。
- 模型信心值；provider 未提供時仍為 `unknown`，不得用內部風險分數冒充。
- 機台異常聲音診斷；目前只能稱聲學訊號離群候選。

這些不是漏做，而是原計畫第 22 節要求由 corpus 實測後建立版本化 ADR。

### 6.3 必須由後續真實驗收補齊

- AV0 真實 V1/V2 基線與 sealed first-run。
- AV2/AV3/AV4 的各 slice 準確率、event coverage、bbox 與矛盾偵測。
- AV5 設備 A 跨來源 Recall@k、authority precedence、version switch 與 revoke。
- AV6 兩人租戶、手機／平板的人工作業負荷與第二人核准。
- AV7 24/72 小時運轉與真實故障注入。
- AV8 實體裝置、弱網、60+60 corpus、tenant truth owner／產品／工程簽認。

因此沒有把外部證據「遺漏」或偷偷降級成單元測試；它們仍是阻擋商用宣稱的明確 Gate。

---

## 7. 建議 rollout

正式環境不得一次全開。建議順序：

1. 先部署 migration，所有新 flags 維持 `false`。
2. 設定 `MEDIA_PIPELINE_V2=true`，但 `MEDIA_V2_TENANT_ALLOWLIST` 只列內部／指定 tenant UUID；名單為空時無任何租戶會啟用，先驗證 analysis run 與 review snapshot。
3. 依序開 `AUDIO_PRECISION_PASS_V1`、`VIDEO_ADAPTIVE_SAMPLING_V1`、`MULTIMODAL_SEGMENT_V1`、`ENTITY_LINKING_V1`。
4. 每次只開一個 capability，跑同一份 regression + tenant shadow corpus，比對 V1/V2 品質、時間、成本與人工負荷。
5. 任一 Gate 退化即關閉該 flag；舊 release 與 V1 artifacts 不受影響。

`.env.example` 與 `.env.production.example` 已加入全部媒體 v2 flags、租戶 allowlist、成本率與上限範本；預設總開關關閉且名單為空。

---

## 8. 最終判定

**工程判定：`SOFTWARE IMPLEMENTATION COMPLETE FOR SHADOW ROLLOUT`。**

**產品認證判定：`NOT PILOT CERTIFIED`。**

理由不是還有隱藏的程式 TODO，而是計畫本身明確要求真實企業內容、實體裝置、長時間運轉與獨立簽認。下一個正確動作是建立乾淨 release、部署 migration 但保持 flags 關閉，接著用指定 tenant shadow rollout 收集 AV0/AV2–AV8 的外部證據。
