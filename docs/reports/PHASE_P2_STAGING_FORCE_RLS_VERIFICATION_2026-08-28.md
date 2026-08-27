# Phase P2 Staging FORCE-RLS Verification

**Verification date:** 2026-08-28（Asia/Taipei；執行紀錄為 2026-08-27 UTC）
**Environment:** 隔離 staging `/opt/enclave-staging`，Compose project `enclave-staging`
**Source commit:** `beffab1f11540ee92e840ce19646a7dd5a849b6d`
**Release:** `staging-beffab1`
**Result:** PASS

## Release identity

| 項目 | 驗證值 |
|---|---|
| Source dirty | `false` |
| Build time | `2026-08-27T16:38:30Z` |
| Deployment manifest | `dm-b2bbaf02edb735ddf2c4152b` |
| Schema head | `p2_tenant_hard_isolation_001` |
| Route contract hash | `5af2bf671476e71a40b148d374217000cf5271c648b6a96e7632e5ddb525b69f` |
| Backend image ID | `sha256:4dc79693b4836cd837113cf704f88bbb7818bd812e06d757c84b26b0cc43772f` |
| Frontend image ID | `sha256:9229b5c94e18389c8e70be86868acf833be2adf32a23b61b5b951f283693606c` |
| Gateway image ID | `sha256:4e088b359a1443f65d95c3120d0a234f1623b25cefcab50bc917870defab3f2a` |

Backend `/health` 與 frontend `/release.json` 的 release、commit、dirty state、schema head 與 route contract hash 完全相符。所有服務在 rollback recovery 後為 healthy；正式環境 `/opt/enclave` 未被異動。

## Deployment and authority boundary

- 以 production-shaped operations profile 依序執行 `migrate`、`provision-db-roles`、`init-superuser`、`init-demo`，再啟動 application services。
- application、maintenance 與 schema owner 使用三組獨立 credential；web、bootstrap 與 Demo seeder 不取得 owner secret。
- `init-superuser` 與 `init-demo` 經 audited maintenance session 寫入 FORCE-RLS schema。
- 100 張 tenant-owned tables 均有 machine-verified policy 並啟用 FORCE RLS。
- application role 非 superuser、無 `BYPASSRLS`；maintenance bypass 需要受稽核 marker 與 transaction context。

## Regression and attack evidence

| 驗證 | 結果 |
|---|---|
| Full backend regression | 1,263 passed／12 skipped／0 failed |
| Frontend Vitest | 25 files／88 passed |
| ESLint／TypeScript／Vite production build | PASS |
| Playwright release-parity and canonical flows | 14／14 passed |
| Tenant policy catalog | 100／100 protected tables |
| Shadow visibility | 3 tenants × 100 tables＝300 comparisons；difference 0 |
| FORCE-RLS attack matrix | 11／11 passed |
| Session-context static gate | PASS |
| Live document／connector／audio／video／DOCX／PDF smoke | PASS |
| Browser canonical asset acceptance | 5 assets；5 個皆為「可搜尋」 |

機器產出摘要 hash：

- Tenant security report: `b4ed8fde42782303eaae832c3a2310af05fd154264643b28c0046ac39dd0258c`
- Session context report: `f5bb12c3823171ca635e07b6c5d3c41d39ef7a5e7feec987d30328b72a69f10b`
- Shadow report: `d6a78140f4fa4ad1cca14e9b4aa430acc1f1e5bd7c5c9755f187e030a9d12b1d`
- Post-rollback gate log: `0bf9f362db9b01023c9e6067fd267b9b0dd6c94e08a37fc97624e7007053ad32`

## Rollback drill

| 項目 | 結果 |
|---|---|
| Start／finish | `2026-08-27T16:41:15Z`／`2026-08-27T16:42:35Z` |
| Duration | 80 seconds |
| Pre／post schema | `p2_tenant_hard_isolation_001` |
| Downgrade target | `knowledge_authority_h1_012` |
| FORCE policies while downgraded／after recovery | 0／100 |
| Backup | `/opt/enclave-staging/backups/p2-rollback-20260827T164115Z.dump` |
| Backup size／SHA-256 | 713,264 bytes／`a63ae195864b27f43bfc400b6efa899b222d50941a714c3bdbb3ba5d091a1604` |
| Rollback report／log SHA-256 | `4756719c1c1c1014ec4cf8203c68a18434b4e2492949adea9de594541c5e8833`／`591905ff87f3cbe7ece099c05b604a7a1434746bba8bf4221160f2b5a43469f6` |
| Post-recovery gateway and full P2 gates | PASS |

## Review findings resolved during staging

1. Production image 缺少 `ffmpeg`／`ffprobe`，會使影片與音訊正式流程失效；已加入映像並以 live multimodal smoke 驗證。
2. persistent upload volume 的 ownership 不符非 root application；已加入受限的 storage initialization。
3. Connector 同步存在 traversal、重複 dispatch、hash normalization、cursor concurrency 與 ambiguous rename collision；均已修正並加入 regression。
4. Gateway throttling 對正常 bootstrap 產生 false positive，且 upstream 429 被轉為 503；已修正並通過 canonical route E2E。
5. FORCE RLS 下 bootstrap／Demo seeder 使用 application identity 會失敗；已改為 audited maintenance session。
6. Demo 文件只存在 legacy `Document`，未出現在 canonical Asset Library；已建立 `SourceAsset`、`AssetRevision` 與 ready `IngestionJob`，瀏覽器驗證 5／5 可搜尋。
7. Compose operations service 曾注入 DB owner secrets；最終版本已移除，並以實際 operations-profile deployment 驗證。

## Decision boundary

本報告證明 P2 staging FORCE-RLS gate 已完成，因此允許進入 P3。這不是 production FORCE-RLS activation 證明；正式環境若要採用本版本，仍須走既有 production deploy、backup、canary、acceptance 與 rollback gate。
