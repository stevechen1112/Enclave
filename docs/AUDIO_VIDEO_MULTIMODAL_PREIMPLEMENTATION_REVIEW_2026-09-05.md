# 音訊與影片多模態計畫實作前複核

日期：2026-09-05
審查標的：`AUDIO_VIDEO_MULTIMODAL_KNOWLEDGE_ENGINEERING_PLAN_2026-09-05.md` v1.1
結論：`PASS FOR PHASED IMPLEMENTATION`

## 1. 審查範圍

- 現有 SourceAsset、AssetRevision、DerivedArtifact、EvidenceSpan、Knowledge Unit、Release、EntityRegistry 與 RetrievalFacade 權威邊界。
- 現行音訊 300 秒切段、ASR、speaker/timecode、影片取幀、OCR、scene、規則候選與聲學離群程式。
- AV0–AV8 的前後依賴、migration、provider、review、retrieval、evaluation、rollback 與外部驗收條件。
- 既有第一租戶 Reality Audit、I5 媒體產品化與 KQ4 typed relation 決策。

## 2. 審查發現與修正

| ID | 發現 | 修正 |
|---|---|---|
| PIR-001 | `media_analysis_runs` 不應被描述成可重建 projection | 明定為不可變作業／溯源紀錄，不具內容或發布權威 |
| PIR-002 | AV8 混合軟體完成與外部實機／人工證據 | 拆成 `SOFTWARE_READY`、`EXTERNAL_EVIDENCE_READY`，兩者皆成立才是 `PILOT_CERTIFIED` |
| PIR-003 | 新 entity links 可能與既有 graph/typed relation 重疊 | 限定使用既有 EntityRegistry；link tables 只是 tenant/revision-scoped projection，所有候選仍由 RetrievalFacade 重驗 |
| PIR-004 | 直接加入高成本 VLM 可能放大不完整輸入 | 保持 AV2 音訊、AV3 取幀／OCR 先於 AV4 multimodal understanding |
| PIR-005 | provider 無信心值時容易再度出現假百分比 | confidence 保持 null；另建具版本、可校準的 quality risk score |
| PIR-006 | 外部真實證據目前不可由工程自行取得 | 不阻止軟體施工，但 capability 與產品宣稱維持 limited/uncertified |

## 3. 可施工性判定

- AV0：可施工。既有 evaluator/corpus contract 可擴充。
- AV1：可施工。需單一新 migration、模型 import、RLS 與 downgrade/forward-recovery。
- AV2：可施工。可沿用 media_productization、voice_gateway、audio task，不另建音訊 authority。
- AV3：可施工。可取代均勻選幀為 provider-neutral sampling plan，保留相容輸出。
- AV4：可施工。先提供 schema-bound provider contract 與保守 fallback；外部 VLM 依 runtime capability 啟用。
- AV5：可施工。以既有 EntityRegistry 與 RetrievalFacade 擴充，不直接查 projection 形成旁路。
- AV6：可施工。沿用 AssetDetail、VideoReview、ReviewQueue，新增同步媒體證據與 critical token 操作。
- AV7：可施工。建立 fault/capacity/cost runner；正式 soak 必須綁定 exact release。
- AV8：認證軟體可施工；外部實機與 tenant truth-owner 證據需由真實測試取得。

## 4. Phase Gate

每一 Phase 必須附：

1. changed-files lint/type/static checks；
2. focused unit/integration tests；
3. migration 或 contract compatibility evidence（適用時）；
4. security、tenant、ACL、release、evidence review；
5. 獨立 Code Review 文件；
6. 計畫 coverage matrix 更新。

任何資料遺失、跨租戶、假完成、無證據發布、錯誤權威優先序或不可回滾 migration 都是 `HOLD`。
