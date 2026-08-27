# Phase P1 — CI、供應鏈與安全自動閘門 Code Review

**Review date:** 2026-08-27  
**Implementation commit:** `2a0ab64517f2d2eaf79690d0f781dbec7cf37b16`  
**Implementation gate:** PASS  
**Security gate:** PASS（未發現未處理的 Critical／High finding）  
**GitHub CI:** `33070946214` / PASS  
**Release provenance workflow:** `33071581045` / PASS

## Conclusion

Phase P1 已建立可重跑、預設阻擋且可追溯的 CI、供應鏈與容器安全閘門。Frontend unit tests、backend type boundary、架構與租戶隔離測試、dependency audit、SAST、secret／pinning policy、license policy、SBOM、三個正式 image build 與 Critical／High container scan 都已納入自動 CI；release workflow 只會在相同 `main` commit 的 CI 成功後執行，並保存 source commit、三個 image digest、SBOM 與 frozen deployment manifest。

本次 review 找到的 High-impact 流程缺口均已在 PASS 前修正。P2 entry gate 開放，但這不代表商業 GA 已完成；租戶硬隔離、完整多模態品質、韌性、可觀測性及 production rollback drill 仍由後續 Phase 驗證。

## Implemented

- 將 frontend `npm test`、產品架構、tenant isolation、mypy product-core boundary 與既有 lint／build／E2E 納入 CI。
- Python 3.13.15、Node 22.23.2、pip 26.2.1、GitHub Actions、Docker base image、Compose sidecar 與 Python dependency 都使用可機器驗證的精確版本或 digest。
- 分離 production 與 test lock，Docker runtime 只安裝 production lock；兩組 lock 均通過 `pip-audit`。
- 將高風險 Bandit gate、tracked-secret scan、supply-chain policy、license policy 與 npm audit 設為 fail-closed gate。
- 產生 CycloneDX 1.5 SBOM 與 NOTICE，release artifact 保存 source commit、三個 image digest 與 frozen deployment manifest。
- Backend、frontend、gateway 三個正式 image 都在 CI 建置並以 Trivy 掃描 Critical／High CVE。
- 將 gateway 納入第一方 image、OCI label、healthcheck、staging／production pull 與 release identity。
- 以 `cryptography` AES-CBC＋PKCS7 取代 PyCryptodome，移除不必要的加密 dependency。
- 將 generic app rate limiting 保留在應用層，edge 專注 auth／chat burst；可信 proxy chain 以由右至左方式解析，避免偽造最左側 `X-Forwarded-For`。
- Frontend 僅在真實 HTTP 401 清除 token；網路中斷或暫時性服務錯誤保留 session。
- Security exception 必須帶 owner 與 expiry；過期或格式不符即使掃描工具忽略也會被供應鏈 gate 阻擋。

## Review findings fixed before PASS

1. **直接信任 `X-Forwarded-For` 最左值會讓外部請求者偽造 rate-limit identity。** 已改為從 direct peer 起向左剝除可信 proxy，遇到 malformed chain 時 fail-safe 使用 direct peer，並加入防回歸測試。
2. **Deployment manifest 若把建置後 image digest 納入自己的 pre-build ID，會形成循環依賴。** 現在 manifest ID 只由精確的 pre-build deployment inputs 決定；三個 image digest 在 build 完成後附加為不可變 evidence。
3. **舊 staging workflow 與 CI 同為 push trigger，註解雖稱「CI 後部署」，實際可能平行執行。** 已改成 `workflow_run`，僅在 CI success 時 checkout 並發布該次 `head_sha`。
4. **CI 使用未鎖定的測試相依與浮動 toolchain，無法完整重現。** 已加入 Linux-resolved test lock，並固定 Python、Node 與 pip 版本。
5. **Repository 追蹤舊的 generated SBOM／NOTICE，容易讓 release evidence 與 source snapshot 混淆。** 已改為每次 gate／release 現場生成並上傳，目錄只保留 `.gitkeep`。
6. **Gateway 雖在 workflow 中建置，初版部署步驟未完整 pull／tag，可能延續舊 edge image。** Staging 與 production 現在都把 gateway 納入三映像 promotion。

## Verification evidence

| 驗證 | 結果 |
|---|---|
| GitHub CI `33070946214` | PASS；6 jobs 全綠 |
| Backend selected product/security regression | 78 passed |
| Frontend unit regression | 25 files／87 tests passed |
| Frontend TypeScript、ESLint、production build | PASS |
| Ruff、mypy boundary、Bandit High gate | PASS |
| Production／test Python dependency audit | PASS |
| NPM dependency audit | PASS |
| Supply-chain／secret／pinning gate | PASS |
| License policy gate | PASS |
| Backend／frontend／gateway local production build | PASS |
| Backend／frontend／gateway Trivy Critical／High scan | 0／0 |
| Release provenance workflow `33071581045` | PASS；三映像發布、SBOM、manifest freeze 與 artifact upload 全綠 |
| Frozen deployment manifest | `dm-2866af23883d1d9bc296df6a`；573 files；dirty entries 0 |
| Release SBOM | CycloneDX 1.5；722 components；source commit 與 workflow head SHA 一致 |
| Workflow YAML parse、Compose config validation | PASS |

Release evidence 記錄的 image digests：backend `sha256:722d5c184f50362db126456ab07a74dc83cab8dba6df8cfb58ad19851c71be4a`、frontend `sha256:c641ac4248864d9c087acc9367048c670f2f0ea585c306fab65eb6656bb07548`、gateway `sha256:7100e65bd330b76c1d4834bef63ecfe506c2e37d794380a709a16efbd0b6f0cf`。

本次 workflow 未執行 staging activation，因 repository 尚未設定 `STAGING_HOST`、`STAGING_USER`、`STAGING_SSH_KEY`；workflow 已明示 unavailable，而不是把未部署偽裝成成功。P1 的 release build／provenance gate 已通過；FORCE RLS staging activation 是 P2 必須另行滿足的 gate。

## Time-bounded exceptions and residual risks

- `PyMuPDF` 為 internal-use 的暫時 license exception，owner 為 `legal-security`、ticket `P1-LIC-001`、到期日 2026-11-30。到期前必須取得正式法律判定、商用授權或替換 dependency；本 Phase 不宣稱已完成商業 GA 法遵核准。
- `.trivyignore.yaml` 有兩項已驗證為 upstream base-image SBOM stale metadata 的例外，owner 為 `platform-security`、到期日 2026-10-31。Final filesystem 不含舊版 msgpack，runtime setuptools 為 84.0.0；例外到期會由 gate 自動阻擋。
- Admin whitelist 在 proxy／NAT 下的網路語意仍需結合 P2 break-glass 與 production topology 統一設計；本 Phase 沒有擴大 tenant superuser 的公開存取面。
- Bandit 與 mypy 現階段採高風險／產品核心 boundary gate；全 repository strict typing 與更廣 SAST 覆蓋可逐步提升，但不是 P1 Critical／High 阻擋項。
- Production digest promotion、資料庫回復與 rollback drill 屬 P6；release provenance 完成不等於災難復原已驗證。

## Gate decision

- **CI／supply-chain implementation：PASS**
- **Critical／High unhandled findings：0**
- **Release provenance：PASS**
- **P2 entry：OPEN**
