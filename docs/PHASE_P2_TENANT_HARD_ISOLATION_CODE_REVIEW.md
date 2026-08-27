# Phase P2 — 多租戶硬隔離與資料生命週期 Code Review

**Review date:** 2026-08-28
**Implementation commit:** `beffab1f11540ee92e840ce19646a7dd5a849b6d`
**Internal implementation gate:** PASS
**Code review:** PASS（Critical／High 未處理 finding：0）
**Staging FORCE-RLS gate:** PASS
**Phase gate:** PASS
**P3 entry:** ALLOWED

## Conclusion

P2 的內部實作、獨立 staging FORCE-RLS 部署與 code review 已完成。系統以 production-like、非 superuser、無 PostgreSQL 原生 `BYPASSRLS` 的 application role 執行攻擊測試；100 張 tenant-owned tables 都有 machine-verified RLS policy，3 個租戶共 300 次 shadow visibility 比對差異為 0。缺 tenant context 看不到租戶資料，跨租戶 raw SQL／ORM／child write 被拒絕，commit 後 context 會自動恢復，stale cache、tombstone、projection、export 與 evidence path 不會讓撤回資料復活。

最終 staging release `staging-beffab1` 已完成三憑證 operations-profile 部署、完整 backend／frontend／worker／connector／多模態與瀏覽器驗證，以及 80 秒 downgrade／upgrade rollback drill。所有 Critical／High-impact finding 均已修正，P2 phase gate 為 PASS，可進入 P3。這項判定不等於 production FORCE activation；production 仍須另走正式部署閘門。

## Implemented

- 新增 tenant security catalog 與 CI gate；未分類 public table、缺 policy、未 FORCE、錯誤 role attribute 或過寬 audit 權限會直接失敗。
- 將 `outbox_events`、`projection_status`、`sync_cursors`、`dead_letter_events`、`gateway_resources` 的隱含 tenant ownership 具體化為非空 FK；migration 對無法判定 ownership 的歷史列 fail closed。
- 將 outbox、projection、sync cursor、gateway mapping 的 uniqueness 改為 tenant-local namespace，避免他租戶以相同 key 造成 collision／DoS。
- application、schema owner 與 audited maintenance 使用獨立 DB login；application role 不是 owner／superuser／bypass member。
- maintenance bypass 同時要求 marker-role membership 與 transaction GUC，且每次寫入 append-only `platform_maintenance_audit`；application 無 audit INSERT，maintenance 無 audit UPDATE／DELETE。
- 登入前 tenant lookup 改為只回傳 tenant UUID 的固定 `SECURITY DEFINER` function，不暴露跨租戶 user row 或 password hash。
- request、retrieval、agent、connector、outbox、reconciliation、knowledge maintenance、audio/video 與 watcher session 都建立 tenant context 或 audited bypass。
- 新增 session-context static gate；任何新的 application session 若沒有 tenant scope，或未列入具理由的 platform-global／health exception，CI 失敗；過期 exception 也會失敗。
- 撤回流程會 tombstone document、asset、wiki、graph 與 downstream resource deny；retrieval cache 命中後仍向 live authority revalidate。
- Compose 與 deploy 改為 `migrate`、`provision-db-roles` one-shot operations；`web` 不再執行 Alembic。
- secrets 分為 `.env.production`、`.env.db-admin`、`.env.maintenance`；web 只收到 application file，worker 才收到 maintenance file，owner file 只進 DB／one-shot operations。
- 全庫備份／還原固定選用 `DB_ADMIN_*`，避免 FORCE RLS 下用 application role 產生不完整備份。

## Review findings fixed before PASS

1. **Outbox／projection／cursor／gateway tables 原本只在 JSON 或 parent ID 隱含 tenant，RLS catalog 無法保護。** 已新增明確 tenant FK、backfill、index、policy 與攻擊測試；ambiguous history 阻擋 migration。
2. **Global uniqueness 在 RLS 下可能讓看不到對方 row 的租戶遭 unique collision。** 四組 idempotency／mapping identity 已納入 `tenant_id`。
3. **部分 retrieval、gateway deny、chat streaming、agent 與 background jobs 自建 session 後未設定 RLS context。** 已逐一補 scope，並以 static gate 防止復發。
4. **Background cross-tenant task 若沿用 application login，FORCE RLS 後會失效；若直接授予 bypass 又過寬。** 已改用獨立 maintenance login、marker role、逐次 audit，再切回 tenant context 執行個別工作。
5. **舊 approval persistence 曾把 actor UUID 當成 tenant UUID。** `ApprovalContext` 現在明確攜帶 tenant，缺 tenant 時拒絕 persistence。
6. **部署原本由 web 容器執行 migration，備份也可能使用受 RLS 限制的 application role。** 已分離 owner operations，部署順序改為 stop → migrate → provision → up，備份使用 admin。
7. **初版三角色雖在程式層分離，單一 env file 仍會把 admin／maintenance 密碼注入 web。** Review 後拆成三個 secrets files，並新增 Compose credential-boundary regression test。
8. **Login role 的 default privileges 會讓未來新建 control-plane table 自動取得 CRUD，重建 audit table 後即可竄改歷史。** 已移除 application／maintenance login 的 future-table default grants；部署在每次 migration 後只對當前 reviewed schema 重新 provision，並新增 future-table 攻擊測試。
9. **舊 regression fixtures 建立 outbox／projection row 時沒有 tenant。** 測試資料已升級為新不變條件，未放寬 FK 或 RLS。

## Verification evidence

| 驗證 | 結果 |
|---|---|
| Fresh database `alembic upgrade head` with FORCE RLS | PASS |
| P2 migration downgrade → upgrade | PASS |
| Tenant catalog／role gate | PASS；100 protected tables，application／maintenance attributes 與 audit grants 正確 |
| Production-like FORCE-RLS attack matrix | 11 passed |
| Shadow visibility report | PASS；3 tenants × 100 tables，difference 0 |
| Tenant boundary matrix | 6 passed |
| Delete／revoke／retention lifecycle | PASS |
| Session context static gate | PASS；5 reviewed global／health exceptions，stale exception 會阻擋 |
| Full backend regression | 1,263 passed，12 skipped，0 failed |
| Post-review deployment／credential regression | 44 passed |
| Compose rendered credential boundary | PASS；web 無 admin／maintenance secret，worker 無 owner secret |
| Workflow YAML parse、Compose config、compileall、diff check | PASS |

最終 staging 同版補充證據：

| 驗證 | 結果 |
|---|---|
| Exact release identity | `beffab1f11540ee92e840ce19646a7dd5a849b6d`；dirty `false`；schema `p2_tenant_hard_isolation_001` |
| Full backend regression | 1,263 passed，12 skipped，0 failed |
| Frontend unit／lint／build | 25 files／88 passed；ESLint、TypeScript、Vite PASS |
| Browser E2E | 14／14 passed |
| Tenant catalog／shadow | 100 protected tables；3 tenants × 100 comparisons；difference 0 |
| FORCE-RLS attack matrix | 11／11 passed |
| Live multimodal smoke | document、connector、audio、video、DOCX、PDF 全部 PASS |
| Canonical Demo UI | 5 assets；5／5「可搜尋」 |
| Rollback drill | PASS；80 seconds；downgrade 後復原 100 FORCE policies |
| Operations credential boundary | PASS；bootstrap services 無 owner secret |

完整 staging 證據與 image IDs 見 `reports/PHASE_P2_STAGING_FORCE_RLS_VERIFICATION_2026-08-28.md`。

一般本機全量測試會在未注入專用 `P2_*_DSN` 時跳過 production-like attack tests；同一批測試已在隔離 staging FORCE-RLS database 以專屬步驟 11／11 PASS。其餘 skip 是明確標示的 optional live-provider／環境型測試，不影響 fresh database migration、CI 與 staging gate。

## Residual risks and production boundary

- P2 已在隔離 staging 以三份實際 secrets 完成 FORCE-RLS 全量回歸與 rollback；尚未把這個工作區版本部署到 production。
- Production 不得把 staging PASS 視為自動發布授權；仍須依 production runbook 執行備份、migration、role provision、canary、release parity、browser acceptance 與 rollback gate。
- 商業 GA 所需的外部滲透、法律與客戶資料／現場驗收不屬於 P2 內部 phase gate。

## Gate decision

- **Internal implementation：PASS**
- **Code review：PASS**
- **Critical／High unhandled findings：0**
- **Staging FORCE full regression：PASS**
- **Phase P2：PASS**
- **P3 entry：ALLOWED**
