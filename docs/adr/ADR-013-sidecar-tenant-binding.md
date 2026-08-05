# ADR-013：Sidecar 租戶綁定（tenant_sidecar_binding）

**狀態**：已接受
**日期**：2026-08-04
**決策者**：Enclave 技術團隊
**關聯**：`CLOUD_AND_COMMERCIALIZATION_PLAN.md` §5.3（WS-SIDECAR-MT）；ADR-001（sidecar adapter）；ADR-003 v2 原則 8

---

## 背景

三個 sidecar 目前都是**部署級單一歸屬**：

- RAGFlow：`RAGFLOW_DATASET_ID` 環境變數全局單一 dataset
- WeKnora：`WEKNORA_KB_ID` 全局單一 KB
- PipesHub：單一 org／JWT bootstrap

形態 A／B（每客戶一套部署）下這沒有問題。形態 C（共享控制面）若沿用全局單一 ID，所有租戶的文件會進同一個 sidecar dataset——**跨租戶資料湖**，且 sidecar 自己的 API 層無法區分租戶（撤權、刪除、稽核全部失效）。這是雲端化計畫中風險等級最高的工作流（R1 極高）。

## 決策

**引入 `tenant_sidecar_binding` 表作為 sidecar 歸屬的唯一權威；所有 sidecar 呼叫必須經 binding 解析，禁止讀取全局環境變數作為租戶歸屬。**

### 具體措施

1. **資料模型**：
   ```text
   tenant_sidecar_binding
     tenant_id        UUID PK/FK
     ragflow_dataset_id   TEXT NULL   -- 未啟用 pack 為 NULL
     weknora_kb_id        TEXT NULL
     pipeshub_org_id      TEXT NULL
     credentials_ref      TEXT NULL   -- credential_vault 參照
     created_at / updated_at
   ```
2. **建立時機**：租戶建立（或首次啟用某 pack）時由 Control Plane 向 sidecar 建立專屬 dataset／KB／org 並寫入 binding；失敗不得半建立（補償清理）。
3. **呼叫紀律**：所有 adapter（`ragflow_http`／`weknora_http`／`pipeshub*`）的公開函式簽章改為必帶 `tenant_id`，內部一律 `binding = get_binding(tenant_id)`；**找不到 binding = raise**（fail-closed），不得 fallback 到環境變數。
4. **隔離不變量**：
   - 租戶 A 的文件不得出現在租戶 B 的 sidecar dataset（上傳／解析／檢索三路徑皆驗證）
   - 文件撤權／刪除時，sidecar 投影經 outbox 收斂（沿用既有 SLA）
   - sidecar 憑證按 binding 的 `credentials_ref` 取用，禁止跨租戶共用 token
5. **遷移**：現有單租戶部署在 migration 中為現有 tenant 建立 binding（值取自現行環境變數），行為不變。
6. **形態 A／B**：binding 永遠只有一列（該客戶），開銷為零；形態 C 才發揮多列作用。

### 明確不做事項

- 不在 Phase 1 做 sidecar 的「多實例池」分派（先邏輯隔離，實例池屬 WS-CAPACITY）。
- 不要求 sidecar 內部做 RLS——隔離邊界在「dataset／KB／org 分開」這一層。
- 不改變「寫入真相在 Enclave PG」：sidecar 永遠是投影，可重建。

## 理由

1. **fail-closed**：無 binding 即拒絕操作，預設安全；錯誤設定在測試期就爆炸，不會靜默串租戶。
2. **單一權威**：歸屬資訊從「散落在環境變數」收斂到一張表，可稽核、可遷移、可重建。
3. **風險前置**：此項為 C 形態最大工程量（R1），依 D1 定案由 AI agent **立即動工**，不等 Phase 2。

## 後果

- 所有 sidecar adapter 呼叫點需加 `tenant_id`（compile-time 可發現；既有呼叫大多已有 tenant context）。
- 測試要求（CG-SIDECAR-MT 閘門）：
  1. 兩租戶各自上傳文件，互相的 sidecar dataset 列表為空
  2. 刪除 binding 後該租戶 sidecar 操作全部 raise（不得靜默落到全局 dataset）
  3. 撤權後 sidecar 投影在 SLA 內收斂
  4. 全局環境變數 `RAGFLOW_DATASET_ID` 等僅用於 migration 種子，運行期讀取視為 defect（CI 靜態掃描）

## 實作備註（2026-08-04，Phase A 落地）

已落地：`tenant_sidecar_bindings` 表＋種子 migration、`app/services/sidecar_binding.py`
（fail-closed 解析）、控制面改造（`document_tasks`／`outbox_worker`／`parse_pipeline`
／gateway router 的 wiki scope 注入）、`crud_tenant.create` 配發空 binding、
**DB 觸發器**（`tenants` INSERT 自動配發——實測發現測試 fixture 直接 INSERT 會
繞過應用層 hook，不變量必須下沉到 DB 層）、11 項測試＋live 種子稽核。

刻意保留的邊界（Form C 強化時收緊）：

1. **Adapter 層的 env 部署級預設**（`ragflow_http`／`weknora_http` 的 env fallback）
   暫保留：adapter 維持無 DB 的純 HTTP 客戶端，且維運腳本（eval／label integrity）
   依賴之。控制面路徑已全部改走 binding（靜態掃描測試把關）；Form C 上線前
   應以部署旗標停用 adapter env fallback。
2. **檢索路徑的 binding 注入非 fail-closed**：binding 缺失時記 error 但不阻斷
   （單租戶部署的 adapter 預設仍正確）。寫入／入庫路徑（document_tasks／
   parse_pipeline／outbox_worker）已是 fail-closed。Form C 前檢索路徑亦須收緊。
3. **Migration 種子的 env 相依**：alembic 在容器外執行時 env 未必載入，
   migration 會 fallback 解析 repo 根目錄 `.env`；皆無則種子 NULL，需補種
   （本開發庫已用部署值回填 50 列）。
4. **Pack provision 流程**（新租戶建立專屬 dataset／KB／org）屬 Phase 2；
   目前新租戶拿到空 binding（pack NULL＝未啟用），解析語意正確但功能未開通。
