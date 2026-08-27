# Phase G Code Review：Legacy 退場、遷移遙測與回滾治理

**Review date**: 2026-08-27
**Gate result**: PASS（退場機制已完成；compatibility observation window 依政策保持開啟）

## Review 範圍

- FastAPI method/path collision 檢查、重複 Job Module endpoint 處置。
- Legacy frontend redirects 的註冊表、租戶級 audit telemetry 與 admin report。
- `observe → warn → disable → remove` gate、30 天零流量條件與不可自動刪除的安全邊界。
- 客戶端升級指南、schema/object-store 回滾要求與操作 runbook。

## 發現與修正

1. **[Critical] `GET /api/v1/job-modules` 同時註冊兩個 handler**
   - 證據：應用 route inventory 顯示 `list_modules` 與 `list_job_modules_with_bindings` 共用同一 method/path，後者永遠不可達。
   - 修正：將 tenant binding/license/config version 合併到單一 canonical handler，移除靜態上不可達的重複註冊。自動測試要求全應用不得再有 method/path collision。
2. **[High] Legacy redirects 只保留相容，無法證明是否仍有客戶使用**
   - 修正：16 個前端相容入口共用唯一 registry，已登入使用者經過舊路由時寫入 tenant-scoped `legacy_surface_used` audit event。
3. **[High] 「近 30 天無命中」報表原本會把更早命中顯示為從未使用**
   - 修正：一次聚合同時回傳 30 天命中數與全期間 `last_used_at`，不遺失歷史證據。
4. **[High] 將「現在沒流量」直接等同「可刪除」**
   - 修正：`observe` 階段在程式上永遠 `removal_eligible=false`；只有審查後進入 warn/disable 且完整 30 天零流量才可開 removal PR。
5. **[High] 全域統計可能掩蓋少數租戶仍使用舊路徑**
   - 修正：API 報表與 CLI audit 都依 tenant RLS 執行；所有活躍租戶都通過才能退場。
6. **[Medium] 回滾文件容易只關心 DB，忽略 immutable object store 與新 artifact kind**
   - 修正：upgrade guide 要求 API/worker 同版、migration 往返、新 artifact kind 相容確認，且明確禁止把 object-store 刪除當成 app rollback。

## 驗證證據

- Phase G gate 測試：5 passed，含 registry 唯一性、observe/warn 日期門檻、FastAPI 全 route collision 檢查、tenant audit/report。
- Experience/Pack 相關回歸：21 passed。
- Frontend：69 passed；production build 與 ESLint 通過。
- `scripts/audit_legacy_surfaces.py --help` 可獨立執行；只讀報表腳本不提供刪除模式。

## 有意保留的相容窗

2026-08-27 所有註冊的 frontend legacy routes 仍為 `observe`，因為之前沒有可信的逐租戶流量數據。本 Phase 的完成代表「退場機制、證據與安全邊界完成」，不代表穿越時間條件強制刪除客戶相容路徑。
