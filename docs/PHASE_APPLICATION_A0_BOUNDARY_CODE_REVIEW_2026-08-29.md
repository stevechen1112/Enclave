# Phase Application A0：應用邊界基準 Code Review

**日期：** 2026-08-29
**結果：** PASS
**範圍：** 核心／Workflow／Application 分層目錄、Pack composition、前端 bundle composition、legacy MKA aggregate freeze

## 1. 本階段完成內容

- 建立機器可讀的 `config/application_boundary_catalog.json`。
- 固定核心能力與 Workflow 能力分類，兩者不得重疊。
- 禁止 `app/platform/**`、`app/ingestion/**` 反向 import MKA Pack、MKA ORM 或 MKA service。
- 禁止 Pack implementation 繞過 `app/composition/packs.py` 被核心直接載入。
- 禁止 MKA frontend bundle 繞過 `frontend/src/modules/installed.ts` 被產品 shell 直接 import。
- 凍結既有 5 個 MKA module key；新場景必須建立 dedicated Pack。
- 舊 module admin API 對未知 module key 回傳 400，不再允許建立 DB-only application。
- 新增 CI architecture gate。

## 2. Code Review 發現與修正

### [High] Seed freeze 可被舊管理 API 繞過

首輪雖已鎖定 5 個 canonical MKA module，但 `ModuleAdminService.register_module()` 仍接受任意 key，管理者可以建立沒有 manifest、UI、API、handler 或生命週期的第六個 DB-only module。

修正後：

- register 僅允許維護既有 5 個 legacy MKA module。
- 未知 key 在 service 層 fail closed。
- API 將此產品邊界錯誤轉為 HTTP 400。
- 新增 regression test，證明 `new_scenario` 無法繞過 dedicated Pack 規則。

### [Low] 本機 Ruff runner 不存在

工作區 `.venv` 沒有 Ruff module／executable，本階段不能聲稱本機 Ruff PASS。此次變更已以 Python compile、pytest、AST architecture gate 與 `git diff --check` 驗證；CI 仍保留 repository 的正式 lint 與完整測試流程。

## 3. 驗證結果

```text
tests/test_application_layer_boundaries.py  5 passed
tests/test_pack_runtime.py                  12 passed
tests/test_experience_bootstrap.py           8 passed
tests/test_p4_module_platform.py            10 passed
合計                                       35 passed
```

- Python compile：PASS。
- `git diff --check`：PASS；只有 Windows LF／CRLF 提示，沒有 whitespace error。
- 未執行瀏覽器驗收：本階段沒有 UI 行為或 route 變更。
- 未執行資料庫 migration：本階段沒有 schema 變更。

## 4. 風險與相容界線

- 既有未知 DB module 若已存在，不會在本階段自動刪除；需在後續生命週期 Phase 盤點與遷移。
- 現有 5 個 MKA module 仍在同一 aggregate，本 Gate 只禁止新增耦合，不代表拆分已完成。
- `ask`、`spec_sop` 與部分影音能力仍有 MKA 相容包裝，將由 A1 搬回核心權威。
- Task、Form、Approval 等共用能力仍依賴 `app.models.mka`，將由 A2 處理。

## 5. Gate 決定

Phase A0 通過，可以進入 A1。A1 必須以核心能力歸位為目標，不得順帶擴充任何場景功能。

