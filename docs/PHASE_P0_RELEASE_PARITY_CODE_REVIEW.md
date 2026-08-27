# Phase P0 — Release Parity Code Review

**Review date:** 2026-08-27
**Implementation gate:** PASS
**Current production activation gate:** PASS
**Production release:** `gh-33065429723-1` / `a86644d3412e75d4d855a8217d3b166ad031aa21`

## Conclusion

Phase P0 的程式、部署與正式環境驗收均已完成：backend、frontend、schema target、實際 Alembic head、route contract 與 source state 已由同一組 release identity 核對；正式網域的 machine parity、authenticated Playwright 與 in-app browser acceptance 全部通過。

沒有發現尚未處理的 Critical／High 問題。P1 entry gate 現在開放；P1 應優先處理本次驗收發現的 NAT-friendly rate limiting、非 401 暫時性失敗不得清除登入，以及 GitHub Actions Node runtime deprecation。

## Implemented

- Backend `/health` 暴露安全的 non-secret release identity。
- Admin operations API 回傳完整 release metadata，並直接比對實際 `alembic_version`。
- Frontend build 產生 `/release.json`，包含 canonical route contract 與 hash。
- Backend／frontend image 接受相同 build args 並加入 OCI labels。
- Release identity 包含 release id、commit、dirty state、build time、deployment manifest、schema head 與 route-contract hash。
- Dirty source build fail closed。
- Staging／production workflow 驗證 backend、frontend、DB schema 與 route contract 同版。
- Production workflow 以 Demo administrator 跑 authenticated canonical-route Playwright smoke。
- 系統「版本更新」頁顯示 release identity 與一致／待確認狀態。
- Explicit emergency rollback 保留 legacy image 的救援路徑；正常發布不能略過 parity gate。

## Review findings fixed before PASS

1. **只檢查 `/health` 與首頁 200 會讓舊 frontend 與新 backend 混版仍顯示成功。** 已加入雙邊 release identity、route contract 與 source commit 核對。
2. **Build-time schema target 不等於 production DB 實際版本。** 已加入 operations API 的 `alembic_version` 比對，CD 也直接執行 `alembic current`。
3. **前後端可能同時來自 dirty source，單純 equality 仍會誤判綠燈。** 現在 dirty source 一律 HOLD。
4. **Production smoke step 未先 `cd /opt/enclave`，故障診斷中的 Compose 指令可能找不到專案。** 已修正 working directory。
5. **嚴格新 metadata gate 可能阻擋緊急回滾到 metadata 上線前的 image。** Explicit rollback 保留 health／frontend smoke 並明示 legacy warning；一般 deploy 仍 fail closed。
6. **Route contract metadata 本身不能證明瀏覽器真的載入路由。** 已加入 production-only authenticated Playwright route smoke。
7. **GitHub 保留 repository 顯示名稱 `Enclave` 的大小寫，直接組成 GHCR 路徑會被 Docker 判為 invalid tag。** Staging／production 已統一使用 lowercase OCI repository `ghcr.io/stevechen1112/enclave`。
8. **Staging workflow 的預設 `GITHUB_TOKEN` 僅有 Packages read，無法 push release image。** 已明示最小權限 `contents: read`、`packages: write`；production 維持 `packages: read`。
9. **Frontend OCI labels 原本只存在 build stage，final nginx image 會遺失 release identity。** 已把 build args 與 labels 移入 runtime stage，並加入防回歸測試。
10. **Authenticated route smoke 以連續 hard reload 測所有路由，會把正常路由驗收誤變成 gateway burst-limit 測試。** 已改為符合實際產品操作的 SPA navigation；限流策略與暫時性失敗登出另列 P1 韌性工作，不以修改測試掩蓋。

## Verification evidence

- GitHub CI run `33065429629`：PASS。
- Backend full regression：**1,220 collected／PASS**。
- Frontend full regression：**24 test files／85 tests passed**。
- Frontend ESLint：PASS。
- TypeScript／Vite production build＋`release.json` postbuild：PASS。
- Ruff（P0 Python scope）：PASS。
- Backend／frontend Docker build check：PASS。
- Release image workflow `33065429723`：PASS；兩個 GHCR image 均發布成功。
- Staging／production workflow YAML parse：PASS。
- Production Alembic：`knowledge_authority_h1_012 (head)`。
- Production machine parity：PASS，0 errors。
- Production Playwright：**3/3 passed**（release identity、direct deep-link shell＋八條 authenticated SPA routes）。
- In-app browser：首頁、Demo 登入、總覽、資產、新增知識、證據審核、品質、功能目錄、資料健檢、版本更新、現場作業、問答均通過；console errors 為 0。
- Production rollback point：`/opt/enclave/backups/enclave_pre_58b7b7a_20260827_105631.dump`，SHA-256 `7116fd86df9a2a1f90bd61345332d8d63507248eba5bfca66e87c6a8aefb265d`，已用 `pg_restore --list` 驗證。

## Pre-deploy negative proof

部署前對舊版 `https://kachu.tw` 執行新的 production-only gate，兩項都依預期 FAIL：

1. `/release.json` 仍回傳 SPA HTML，不是 release metadata JSON。
2. Demo administrator 開啟 `/knowledge/assets` 會回到 `/`。

這證明 gate 能抓到 production 與候選 baseline 不同版，而不是只靠首頁 200 產生假綠燈；部署 `a86644d` 後，相同 gate 已轉為 PASS。

## Gate decision

- **Code／workflow implementation：PASS**
- **Current production parity：PASS**
- **P1 entry：OPEN**
