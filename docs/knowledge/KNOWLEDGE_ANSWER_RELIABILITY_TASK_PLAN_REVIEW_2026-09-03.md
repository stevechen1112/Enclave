---
title: "Knowledge Answer Reliability Task Plan v1.1 文件複查"
document_type: "plan_review"
language: "zh-TW"
date: "2026-09-03"
reviewed_document: "docs/KNOWLEDGE_ANSWER_RELIABILITY_TASK_PLAN_2026-09-03.md"
reviewed_version: "1.1"
conclusion: "PASS — REQUIRED REVISIONS RESOLVED; AWAITING EXPLICIT OWNER AUTHORIZATION TO START KQ0"
---

# Knowledge Answer Reliability Task Plan v1.1 文件複查

## 1. 複查結論

**PASS — REQUIRED REVISIONS RESOLVED；等待 Owner 明確指示「開工」後才可開始 KQ0。**

v1.1 已完整處理第一次複查的七項 required revisions，並維持 Enclave 原有架構邊界。本結論只代表計畫文件已具備可執行性，不是 `KQ-BL-01`、任何 KB gate、部署、正式 Shadow 或 enforce 核准。

截至本次複查：KQ0 尚未開始，未實作 KQ0–KQ7、未部署、未修改正式環境，也未變更 Input I9 或李永仁第二輪真實測試路徑。

## 2. 複查依據

本次逐份完整閱讀並交叉核對：

- `docs/KNOWLEDGE_ANSWER_RELIABILITY_TASK_PLAN_2026-09-03.md`
- `C:/Users/User/Desktop/AIHR技術成果與Enclave通用知識庫轉用建議_20260903.md`
- `docs/ENCLAVE_ENTERPRISE_KNOWLEDGE_BASE_ENHANCEMENT_PLAN.md`
- `docs/knowledge/IMPLEMENTATION_AND_CODE_REVIEW_2026-08-25.md`
- `docs/knowledge/EXISTING_CAPABILITY_DISPOSITION.md`
- `docs/adr/ADR-014-queryspec-evidence-contract.md`
- `docs/adr/ADR-018-sealed-eval-production-shadow.md`
- `docs/adr/ADR-020-knowledge-pack-boundary.md`

## 3. Required revisions 關閉紀錄

| # | 第一次複查要求 | v1.1 修訂 | 複查結果 |
|---|---|---|---|
| 1 | KQ3 decision diff 必須兼顧 read-only Shadow 與管理介面 | 指定 tenant operational DB 外的 evaluation artifact／telemetry store；append-only、傳輸中與靜態加密、tenant-scoped access、retention、legal hold、purge audit；管理端只經授權服務唯讀查詢。writer 故障不得 fallback 寫 tenant DB。 | CLOSED |
| 2 | KQ-SHADOW-01 樣本與門檻不足 | 明訂至少 30 個真實案例、2 個 subject、4 個 deny／forbidden 負例；首次正式 Shadow 前凍結 false rejection、false acceptance、latency P50/P95/P99、execution failure、sync/stream parity 與停止條件，首跑後不可回調。 | CLOSED |
| 3 | KQ4 正式 Ask admission 不完整 | 明訂只讀 `quality_state=ready`、`KnowledgeUnitRecord.status=active`、`KnowledgeUnitRelease.status=active`、`membership.status=active`；候選進 decision 與 claim/citation 核發前再次檢查 ACL、exact revision、deny/tombstone。 | CLOSED |
| 4 | 候選租戶與 enforce 授權混淆 | 候選 tenant 需 Owner 可稽核核准；shadow 與 enforce 分成兩次授權。八策僅是候選，完成 Shadow、tenant acceptance、權限負例與回滾確認後仍須另取 enforce 核准。 | CLOSED |
| 5 | baseline JSON 不應置於 docs | JSON 改為 `artifacts/knowledge/KQ_BASELINE_MANIFEST.json`；`docs/knowledge/KQ_BASELINE.md` 只保存說明、重現方式、敏感資料邊界與相對 manifest reference。 | CLOSED |
| 6 | Shadow 關閉後成本敘述過度絕對 | 改為請求路徑不再執行 shadow decision/diff/provider/model，且不再產生模型成本；依法或依政策保留的 artifact 仍依 retention 占用加密儲存。 | CLOSED |
| 7 | 修訂需納入版本控制並建立 Review | Task Plan 標記為 v1.1、加入版本紀錄，並建立本複查文件；版本控制提交另以實際 commit 識別。 | CLOSED |

## 4. 架構與產品邊界複查

### 4.1 通過項目

- 多租戶、多元 Input 與 Enterprise Knowledge Kernel 持續是不可拆核心。
- Knowledge／Domain Pack 只透過標準 contribution 擴充，可安裝、停用與移除；不得繞過 core ACL、revision、EvidenceContract 或 RetrievalFacade。
- KQ0–KQ7 是 Live Ask 收斂至唯一 `EvidenceDecision` 的增量計畫，不重做已施工 K0–K10。
- `EvidenceOrchestrator` 是最終 decision 的唯一 owner；`retrieval_coverage.py` 只保留 adapter／shadow comparator 的退場定位。
- Knowledge Unit、KB revision、RetrievalFacade、CitationBuilder、ACL 與 release 繼續是 canonical authority；沒有新增平行 graph、retrieval、revision 或 citation 真相。
- AIHR `hr_pv_t0_*`、優利題目、固定答案、HR 文件家族與手工特判均維持禁止進入 Enclave core。
- 每個完整 KQ phase 仍須依序完成實作、測試與獨立 Code Review；Review 未通過不得進下一 phase。

### 4.2 一致性判定

v1.1 與 ADR-014 的 server-owned EvidenceContract、ADR-018 的 sealed first-run／production Shadow、ADR-020 的 Pack 去耦，以及既有能力處置矩陣相容。新增的 out-of-band append-only store 是 Shadow evaluation artifact 的保存邊界，不是第二套 tenant knowledge、conversation、revision 或 retrieval authority。

## 5. 啟動前狀態

目前狀態為 **READY FOR OWNER START DECISION**，不是開工。

Owner 若在新任務明確說「開工」，第一個允許執行的範圍只有 KQ0：基線凍結、AIHR→Enclave mapping、呼叫圖、污染掃描與 `KQ-BL-01` 文件／測試／Code Review。KQ0 不得改正式答案、不部署新 decision，且不得干擾 Input I9 第二輪真實測試。
