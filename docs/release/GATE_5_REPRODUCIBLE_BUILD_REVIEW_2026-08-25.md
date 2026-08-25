# Gate 5 — 可重建來源、候選映像與 Code Review

日期：2026-08-25
結論：**PASS**（正式站尚未部署；候選映像只存在本機）

## 本關交付

- 將原本 284 項工作區變更收斂成可追溯來源 commit。
- 將每次測試產生的 `*_last_run.json` 移出版本控制，只保留經人工確認的 K0 基準與歷史評測凍結資料。
- 移除過時的一次性遠端修補、資料清理與除錯腳本；檔案仍可從舊 Git 歷史取回，但其中曾使用過的憑證不得再使用。
- 六道門改用固定合成 Demo 租戶、內部 `.invalid` 身分與短效權限 token，不再依賴共享帳號密碼。
- 發布來源閘門會掃描高可信度金鑰格式，也會以 SHA-256 指紋攔截三組已知洩漏／共用的舊憑證，報告不輸出憑證內容。
- PDF fixture 被明確標記為 binary，移除 Windows 自動換行造成的假變更。

## 可重建證據

- 來源基準 commit：`beb5904ae4ac38e065fa0fc0b91cc0f1e27d4c78`
- 後端候選映像：`enclave-backend:rc-20260825-gate5`
  - Image ID：`sha256:433e154d931315466a18311e68c7f5146b4f8eef46237c7fd732c856906557ad`
  - 大小：476,546,745 bytes
  - 執行使用者：`enclave`
- 前端候選映像：`enclave-frontend:rc-20260825-gate5`
  - Image ID：`sha256:09992c35d00deedb0b47b0f288ccfd0f2bd942d59ea2a77821ce6cc92c7be813`
  - 大小：42,024,328 bytes
  - 執行使用者：`nginx`
- 發布清單（preflight）：482 個部署輸入檔，backend 338、frontend 131、gateway 13；部署來源 dirty 數 0。
- SBOM 工具：Syft 1.51.0，映像 digest `sha256:678bfa565b60f747aac0f8e964fe5588a24445b8d0a480e91f6efd70020dfbb0`。
- SBOM：後端 487 packages、前端 69 packages，存放於被 Git 忽略的 `artifacts/release/`。

## 驗證結果

- Gate 1–5 聚焦後端回歸：181 passed、1 skipped。唯一 skip 是本機 live PostgreSQL 尚未套用 `tenants.is_demo` migration；Gate 6 必須先升級隔離測試資料庫再重跑，skip 不算最終驗收。
- Demo／Sidecar／來源閘門小組回歸：23 passed、1 skipped。
- 前端單元／元件測試：47/47 passed。
- 前端 ESLint：PASS。
- 前端 production build：PASS。
- 本次 223 個變更／新增 Python 檔之阻斷級 Ruff（E9、F63、F7、F82）：PASS。
- `compileall`：PASS。
- `git diff --check`：PASS。
- 1,532 個追蹤來源檔的高可信度敏感資料掃描：0 findings。
- 發布來源 preflight（尚未要求 tag）：PASS，0 errors。
- 後端映像 import smoke：PASS；資料庫與 Redis 缺席時採 fail-safe 模式。
- 前端映像在具有 `web` upstream 的隔離 network 中：`nginx -t` PASS、首頁 HTTP 200。

## Code Review 發現與處置

1. **已修正：Sidecar live test 依賴測試順序。** 測試現在於 transaction 中自行重建合成 Demo；若 migration 尚未套用會明確 skip，而不是以「資料不存在」誤報產品錯誤。
2. **已修正：Demo 管理者寫入 allowlist 路徑錯誤。** 現在只允許指定簽核決策路徑，其他政策與知識寫入仍 fail closed，且以真實 middleware integration test 驗證。
3. **已修正：二進位 fixture 受到 CRLF 轉換。** `.gitattributes` 使用 `*.pdf binary`，目前 fixture hash 已回復 HEAD。
4. **已修正：內建 Docker SBOM 外掛與 daemon API 不相容。** 未採用 0-byte 輸出，改用 digest 固定的 Syft 容器並驗證 JSON package 數。
5. **保留且揭露：全專案 Ruff 有 5,434 個既有問題。** 多數位於未修改的舊代理與舊測試程式；本關不以大規模自動修復擴張變更。本次來源已通過阻斷級規則，完整 lint 債需在後續品質治理獨立收斂，不能宣稱全專案 Ruff 已通過。
6. **Gate 6 阻斷條件：** 必須套用完整 migration、消除 live test skip、執行 1,039+ 後端完整回歸與六角色瀏覽器流程。未達成前不得進入真實 Z5／容量與正式 Shadow。

## 最終封存程序

本報告 commit 後，重新凍結 deployment manifest，使 `source_commit` 指向最終 HEAD；因 `docs/` 不屬於後端或前端映像 build context，也不屬部署輸入清單，報告 commit 不改變上述映像內容。最終 release tag 與嚴格 `RELEASE-SOURCE` PASS 共同構成本關放行證據。
