# 應用層脫鉤實作計畫

**日期：** 2026-08-29
**狀態：** Approved implementation baseline
**產品決策：** 核心持續增強；場景應用必須可選、可替換、可停用並最終可乾淨移除

**實作進度：** A0 PASS；A1 PASS；A2 PASS；A3 PASS；A4 PASS

## 1. 目標結構

```text
Multi-tenant Control Plane
  ├─ identity / tenant / ACL / RLS / audit / quota
  └─ entitlement / experience bootstrap

Core Input + Enterprise Knowledge
  ├─ file / image / audio / video / capture / connector
  ├─ Asset / Artifact / KnowledgeUnit / Evidence / Release
  └─ Ask / citation / refusal / spec-SOP mode

Workflow Kernel
  └─ task / form / approval / todo / notification / export

Independent Applications
  └─ own manifest / UI / API / handlers / data policy / tests
```

依賴只能由下往上使用公開 contract：應用可以使用 Workflow 與核心，Workflow 可以使用多租戶控制面，但核心不得知道報價、異常、8D、師傅傳承或任何租戶專屬業務名詞。

## 2. Phase A0：邊界基準與防回退 Gate

### 實作

- 建立 `config/application_boundary_catalog.json`，以機器可讀方式宣告核心、Workflow、應用與既有技術債。
- `app/platform/**` 與 `app/ingestion/**` 禁止 import `app.packs/**`、`app.models.mka` 或 `app.services.mka_*`。
- Pack implementation 只能被自己的 package 或 `app/composition/packs.py` 組裝。
- 前端 Pack bundle 只能由 `frontend/src/modules/installed.ts` 組裝。
- 既有 5 個 MKA module key 凍結為 `frozen_pending_split`；禁止把新場景直接加入大型 MKA seed。
- 舊管理 API 只能維護這 5 個相容模組；未知 module key 必須拒絕，不能建立沒有 Pack manifest 的 DB-only 應用。
- 將 Gate 納入 CI 的產品架構測試。

### Gate

- 新增 architecture tests 全部通過。
- 現有 Pack runtime、experience bootstrap 與租戶模組測試不回歸。
- `git diff --check`、測試與 code review 通過後才進 A1。

## 3. Phase A1：核心能力歸位

- `ask` 不再是 MKA Task 或租戶選配 module。
- `spec_sop` 改為 Ask 的核心 scope／mode，不是場景應用。
- 錄音、長音訊轉錄、圖片與影片知識化移入核心 Input／Knowledge contract；應用只能發起目的導向流程。
- 移除核心 Knowledge read path 對 `TenantModuleBinding` 的直接依賴，改由通用 capability／policy context 判斷。
- 保留舊 URL 與 task key 相容層，但不得成為新權威。

## 4. Phase A2：Workflow Kernel 抽離

- 將 TaskDefinition、TaskRun、FormDefinition、FormInstance、Approval、Todo、Notification 與 Export 的共用 contract 從 MKA 命名空間抽出。
- 將 ORM、repository、service 與 API 按 Workflow 所有權重新定位；舊 import 只作受控相容轉接。
- Workflow 不包含報價、異常、8D、訓練等欄位或狀態。
- 任一應用只能透過版本化 Workflow contract 註冊 task、form、rule 與 approval policy。

## 5. Phase A3：獨立應用契約

每個通過產品驗證的應用必須擁有：

- application／pack manifest 與 semantic version。
- 唯一 route、API、handler、permission 與 capability key。
- 明確資料所有權、保留、匯出、封存及刪除政策。
- install、enable、disable、archive、remove lifecycle hook。
- 租戶預設設定與受控 extension point。
- 權限、跨租戶、升降版、停用與移除測試。

既有 MKA 不再新增第六個場景；新應用一律建立 dedicated Pack。

## 6. Phase A4：生命週期與最終驗收

- 停用後 navigation、route、API、worker、provider、action 與排程全部 fail closed。
- 封存保留歷史讀取與 audit，但禁止建立新資料與執行背景工作。
- 移除前必須提供匯出、依賴分析、資料處置選擇與可回復計畫。
- Base-only、單一應用、兩個應用並存及租戶客製應用組合均完成驗收。
- 證明移除任一應用不影響 Input、Knowledge、Ask、Evidence、Workflow 或其他應用。

## 7. 執行原則

- 不因現有程式存在就批准應用繼續存在。
- 不在產品驗證前重寫場景 UI 或擴充場景功能。
- 不一次搬動資料權威；每次先建立 contract、dual path、驗證與回復點。
- 每個完整 Phase 必須完成實作、測試、code review、修正與獨立 review 文件後才進下一階段。
- 工作區既有未相關變更不納入本計畫提交。
