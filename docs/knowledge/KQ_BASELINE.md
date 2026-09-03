# KQ0 Knowledge Answer Baseline

日期：2026-09-03
Gate：`KQ-BL-01`
目前狀態：`BLOCKED`
限制：KQ0 only；Live Ask runtime behavior unchanged

## 目的

本基線凍結 Knowledge Answer Reliability 施工前的 Ask schema、sync/stream 路徑、legacy decision、離線代表案例、known failures、canonical owner 與核心污染狀態。JSON 不放在 `docs/`；本文件只提供說明、重現方式與 artifact references。

## Artifact manifest

唯一入口：`../../artifacts/knowledge/KQ_BASELINE_MANIFEST.json`

Manifest 以 SHA-256 指向：

- `KQ_API_SCHEMA_SNAPSHOT.json`：`POST /chat` 的 Pydantic request/response schema，以及 `POST /chat/stream` 的 SSE event contract。
- `KQ_CALL_GRAPH.json`：sync/stream、檢索、legacy coverage、SourceVerifier 與資料寫入的 source anchors。
- `KQ_BASELINE_OUTPUTS.json`：13 類 synthetic、deterministic、offline 案例的 QueryPlan、legacy decision、sync fallback 與 stream fallback。
- `KQ_KNOWN_FAILURES.json`：11 項已確認差距及目標 KQ phase。
- `KQ_CORE_CONTAMINATION_SCAN.json`：generic core 掃描結果、禁止清單與具名 waiver。

## 代表案例

固定矩陣包含：direct fact、exhaustive list、partial、absent、insufficient context、conflict、comparison、procedure、table same-row、wrong scope、wrong revision、provider failure、multi-turn。

這些案例只保存合成問題與合成證據，不含租戶內容。其目的不是證明品質，而是凍結目前行為，其中包括目前會錯誤放行或錯誤歸類的 known failures，例如：

- insufficient context 仍可能得到 `answer`，沒有獨立 clarify state；
- conflict、wrong scope、wrong revision 仍可能被 legacy coverage 判為 `answer`；
- provider timeout fixture 會落成 `abstain` 形狀，沒有正交 ExecutionStatus；
- closed-list 與 per-entity coverage 未被 legacy regex 證明。

## 呼叫圖結論

- sync：`POST /chat → ChatOrchestrator.process_query → retrieve_context → MultiStepOrchestrator → RetrievalFacade → _build_context → retrieval_coverage → sync generation/fallback`。
- stream：`POST /chat/stream → retrieve_context → MultiStepOrchestrator → RetrievalFacade → _build_context → retrieval_coverage → stream_answer`；只有 `SOURCE_VERIFY_MODE=shadow|enforce` 才進 SourceVerifier。
- `EvidenceOrchestrator.decide_evidence` 目前只有測試呼叫，尚未是 Live Ask owner。
- 一般 Live Ask endpoint 會建立 conversation/message、retrieval trace 與 usage；未來 KQ3 read-only shadow 不能直接重用這條持久化路徑。

## 污染掃描

本輪掃描 `app/services`、`app/api`、`app/agent`、`app/gateway`、`app/platform` 共 271 個 Python 檔案：

- 未豁免 runtime finding：0。
- 具名 waiver：10。
- 9 個 waiver 是既有 regression provenance comment/docstring，不參與執行。
- 1 個 waiver 是 `structured_answers.py` 的既有 HR compatibility 技術債；Owner、flag 邊界及退場條件已登錄。KQ1+ 不得新增 waiver。

完整禁止 pattern 與逐項 waiver 以 `KQ_CORE_CONTAMINATION_SCAN.json` 為準。

## 重現方式

在 repository root 執行：

```powershell
.\.venv\Scripts\python.exe scripts\freeze_knowledge_answer_baseline.py --check
.\.venv\Scripts\python.exe -m pytest tests\test_knowledge_answer_kq0.py -q
```

工具不連 DB、不呼叫 provider、不建立 conversation/message、不寫 cache/usage/feedback，也不部署。它只在 `artifacts/knowledge/` 重建 KQ0 artifact。

## 為何 Gate 仍是 BLOCKED

Repository 內最新可用的正式 baseline 是 2026-08-24 的 read-only evidence；另有不同時間與不同 image identity 的 acceptance/predeploy artifacts。它們可供 lineage 參考，但無法證明 2026-09-03 當下正式環境仍使用同一 image、KB revision、Knowledge Unit release 與 Pack versions。

`KQ-BL-01` 仍缺：

1. authorized operator 產生的 2026-09-03 新鮮正式唯讀 snapshot；
2. exact backend/frontend image、deployment manifest、prompt/model/flags；
3. exact active KB revision、Knowledge Unit release/membership 與 Pack versions；
4. snapshot 前後 mutation sentinel，證明正式 tenant row/digest delta = 0。

取得上述證據前，KQ1 不得開始；不得以歷史 artifact、local test DB 或開發者自行宣告取代。
