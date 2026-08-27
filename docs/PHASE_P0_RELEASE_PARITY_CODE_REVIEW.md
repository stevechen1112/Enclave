# Phase P0 — Release Parity Code Review

**Review date:** 2026-08-27
**Implementation gate:** PASS
**Current production activation gate:** HOLD（正式站仍是較早 release；尚未執行本次 deployment）

## Conclusion

Phase P0 的程式與部署閘門已完成：backend、frontend、schema target、實際 Alembic head、route contract 與 source state 現在可被同一組 release identity 核對；正式 CD 也加入 authenticated canonical-route Playwright smoke。

沒有發現阻擋程式合併的 Critical／High 問題。依 phase sequencing 規則，P1 不應在 P0 production activation PASS 前開始；下一個動作是用新流程建立 clean release、部署，再讓 shell parity 與 browser smoke 同時通過。

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

## Verification evidence

- Backend full regression：**1,217 passed**，7 個既有第三方 deprecation warnings。
- Phase P0 focused backend：**13 passed**。
- Frontend full regression：**24 test files／85 tests passed**。
- Frontend ESLint：PASS。
- TypeScript／Vite production build＋`release.json` postbuild：PASS。
- Ruff（P0 Python scope）：PASS。
- Backend／frontend Dockerfile `docker build --check`：PASS，0 warnings。
- Staging／production workflow YAML parse：PASS。
- `git diff --check`：PASS（僅 Windows LF→CRLF notice）。

## Negative production proof

對目前 `https://kachu.tw` 執行新的 production-only gate，兩項都依預期 FAIL：

1. `/release.json` 仍回傳 SPA HTML，不是 release metadata JSON。
2. Demo administrator 開啟 `/knowledge/assets` 會回到 `/`。

這證明 gate 能抓到現有 production 與目前工作區最新 baseline 不同版，而不是再次只靠首頁 200 產生假綠燈。

## Gate decision

- **Code／workflow implementation：PASS**
- **Current production parity：HOLD**
- **P1 entry：HOLD，直到新 release 部署後兩個 production smoke tests 均 PASS**
