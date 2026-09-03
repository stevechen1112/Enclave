# KQ0 Knowledge Answer Baseline

日期：2026-09-03
Gate：`KQ-BL-01`
目前狀態：`PASS TO NEXT PHASE`
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
- `KQ_PRODUCTION_OPERATOR_SNAPSHOT.json`：正式 release、runtime、KB／Knowledge Unit release、Pack 版本及 mutation=0 唯讀證據。

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

## Gate 解除證據

2026-09-03 由既有 `kachu` operator SSH profile 對正式容器執行兩組唯讀 probe，並核對公開 `/health` 與 `/release.json`。正式 release 為 `input-i9-dd5a6bd`，source commit、backend/frontend/gateway image digest、deployment manifest、prompt/model/flags、active KB revision、Knowledge Unit release/membership 空集合及五個 Pack 版本均已凍結。

取證具備：

1. `SET TRANSACTION READ ONLY` 為 true；
2. 前後 `snapshot_digest` 完全相同；
3. 舊版文件／ACL probe 前後 digest 亦相同；
4. production writes 與 deployed changes 均為 0；
5. 本機隔離 PostgreSQL 的兩個先前阻塞測試已重跑並 2/2 通過。

因此 `KQ-BL-01` 已解除，允許開始 KQ1；本證據不構成 KQ3 Shadow 或 KQ7 enforce 授權。
