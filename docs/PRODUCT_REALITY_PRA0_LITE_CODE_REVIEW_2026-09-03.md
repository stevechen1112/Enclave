# Product Reality PRA0-Lite 實作與 Code Review

日期：2026-09-03
範圍：可自動化、直接改善產品真實性的工程工作；不把書面簽核、外部法律或客戶簽認當作開發完成條件。

## 結論

本輪完成 PRA0-Lite inventory、current-release 合成核心旅程、自動化權限／撤權負面回歸、PostgreSQL FORCE RLS 隔離驗證，以及小型非破壞性 production probe runner。PRA0-Lite 文件漂移已清零。

Code Review 找到並修正兩個 P1：

1. Viewer 在沒有 active KB revision 的 shadow 情境讀取文件清單／單筆文件時，會因直接取用不存在的 `kb_revision_ids` 而 500。現在兩條路徑皆 fail-closed，回歸通過。
2. P2 之後新增的 11 張 tenant table 沿用只檢查 `app.bypass_rls=on` 的舊 policy。新增 `tenant_policy_reconcile_pra_001`，必須同時具備 audited bypass marker role 才能繞過。

在隔離 PostgreSQL 上由空資料庫升到新 head 並啟用 FORCE RLS，111 張表的 machine gate、11 項攻擊矩陣、2 tenants × 111 tables 共 222 組 shadow comparison 全部 PASS、差異 0。臨時資料庫及登入角色已刪除。

## PRA0-Lite inventory

- API routes：347
- Frontend routes：23
- Background tasks：20
- Feature flags：45
- Application packs／knowledge contributions：9
- Connector contracts：3
- Provider roles：7
- 文件漂移：0
- Production backend／frontend／runtime manifest identity：一致

權威 artifacts 位於 `artifacts/product_reality/`。Registry 只表示程式或 runtime inventory，不把「存在」推論為真人驗收或商業價值成立。

## Current-release 核心旅程

正式 release `kq7-complete-f08884d` 已以內部 synthetic tenant 完成：登入 → upload → terminal ready → search hit → grounded Ask（7.25 mm、2 sources）→ revoke → asset 404 → search identity 不殘留。資料 marker、asset 與 document 已清除。

最終新 release 部署後必須再跑一次，舊 artifact 只保留為該精確 release 的歷史證據。

## 容量與韌性邊界

容量、遙測、queue、integrity、degradation 與 resilience 的 70 項自動化控制全部通過；另新增硬上限 50 concurrency／200 requests 的 production non-destructive probe runner。

這不等於 P5 正式容量認證。混合 upload／audio／video 負載、故障注入與 72 小時 soak 只能在專用隔離 staging 執行，禁止拿 production 補做。它們也不回寫成一般開發完成率，但在對外宣稱容量或 SLA 前仍必須有實測數據。

## 尚未關閉的工程風險

正式部署目前仍以 `postgres` 超級使用者作為 application DB login，且 `RLS_ENFORCEMENT_ENABLED=false`。現況適用專屬部署，不具 shared multi-tenant 資料庫層強制隔離宣稱。

新 policy migration 可先安全部署；application role 切換與 FORCE rollout 必須先在同版 production-like canary 驗證 API、worker、scheduler、connector 與維運 bypass，再切正式 credentials。這是實際工程風險，不是書面 Gate。
