# 仍開放閘門（整份計畫未閉環項）

> **流程強弱整合視圖**：`docs/PIPELINE_STRENGTH_MAP.md`（逐環節評級＋證據＋宣稱邊界；本文件是閘門清單，強弱判讀看那份）。

同步來源：`DEVELOPMENT_PLAN_TRIPLE_INJECTION.md`、`docs/PLAN_PROGRESS.md`、`artifacts/plan_progress_last_run.json`。  
能力啟用／增量價值閘門（CV-*）：見 `docs/CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md`（與下方商業 GA 人工閘門互補；舊 checkbox PASS 不自動等同 CV PASS）。

> **真治本（檢索粒度／融合／入庫交付）**：見 `docs/FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN.md`  
> ADR：`ADR-008`（多粒度）、`ADR-009`（融合不變量）、`ADR-010`（入庫交付）。  
> 閘門 ID：`FD-DELIVER`／`FD-CATALOG`／`FD-FUSION`（**不得**以題號特判或關 WeKnora 當完成）。  
> 願景總綱：`docs/VISION_POINT_A_TO_B.md`（與能力消融計畫互補，見該文件 §與 CAPABILITY 的差異）。  
> 雲端化／商業產品化（**✅ Accepted 2026-08-04，D1–D7 全定案**）：`docs/CLOUD_AND_COMMERCIALIZATION_PLAN.md`（閘門 ID：`CG-*`／`HG-PENTEST-CLOUD`）。  
> ADR：`ADR-003 v2`（SaaS 邊界擴張）、`ADR-011`（storage backend）、`ADR-012`（tenant RLS）、`ADR-013`（sidecar 綁定）。  
> 2026-08-04 Phase 1 動工：**CG-STORAGE 程式層完成**（StorageBackend 抽象＋local/S3 雙實作＋測試；雙路徑驗收待雲端帳號）；**CG-RLS shadow 落地**（27 表 policy 已建、未 FORCE；live 繞過攻擊測試全綠含 commit 存活實證；superuser 跳過 RLS 已列 ADR-012 硬性部署前提）；**CG-SIDECAR-MT Phase A 落地**（binding 表＋DB 觸發器不變量＋控制面 fail-closed 解析＋靜態掃描把關；pack provision 流程屬 Phase 2）。  
> 2026-08-04 code review：Bugbot 5 findings（3 高 2 中）全部修補並加回歸測試——RLS context 跨 commit 存活（after_begin 監聽器）、audit bypass 洩漏、上傳孤兒記錄、login 缺 bypass、worker S3 租戶前綴檢查。  
> 2026-08-05 **CG-QUOTA 落地**：串流主路徑 `/chat/stream` 補上配額強制（原先只擋非串流，屬假綠）；查詢＋token 雙軸 429；儲存軸由 `file_size` 累計（原寫死 0）；方案矩陣對齊計畫 §3.3（pilot/team/business/enterprise，保留 free/pro 相容）；用量儀表沿用 admin/company 既有端點；532 tests 全綠。  
> 2026-08-05 **CG-AUTH-SSO 落地**：SSO router 掛載且 callback 完成登入閉環（IdP userinfo→email 連結既有帳號→核發含正確 tenant 的 JWT；fail-closed：網域白名單、預設不自動開戶、跨租戶連結 403）；`TenantSSOConfig` 模型重建＋owner/admin 設定端點；email 驗證（HMAC token＋SMTP/log 雙模，`EMAIL_VERIFICATION_ENABLED` 開啟時未驗證不可聊天）；owner MFA（stdlib TOTP、partial token 雙 scope，`get_current_user` 一律拒絕局部 token＝挑戰不可繞，`MFA_ENFORCE_OWNER` 強制開通流程）；migration `p5_auth_hardening_001` 已套用（既有用戶回填已驗證）；555 tests 全綠。  
> 2026-08-05 code review 修補（Bugbot 6 findings）：SSO callback 改走 `build_login_response`（不可繞 MFA）；`auto_create_user` schema 預設改 false；Microsoft 只接受 `mail`／非 #EXT# UPN；儲存軸上傳強制；聊天配額 `reserve_chat_quota`（FOR UPDATE 原子預留）；SMTP 未設時不寫驗證 token 至 log；561 tests 全綠。  
> 2026-08-05 **CG-OBS 落地**：Sentry（web＋worker，`SENTRY_DSN` 未設則 no-op）；Langfuse 問答 trace（retrieval／generation／source_verification span 串聯）；Prometheus 業務指標 `enclave_quota_exceeded_total`、`enclave_source_verify_total`；569 tests 全綠。  
> 2026-08-05 **CG-CLAMAV 落地**：`file_scan.py`（ClamAV INSTREAM）；上傳端點整合（惡意 400、fail-closed 503）；`compose/clamav.yml` overlay；production/staging + `CLAMAV_FAIL_CLOSED` 啟動檢查；576 tests 全綠。  
> 2026-08-05 **託管 POC 實例（Phase 1）**：`docs/runbooks/MANAGED_PRIVATE_CLOUD.md`（Compose 拉起／開戶／交付 SOP）；`scripts/managed_poc_smoke.py`（煙霧閘門 → `artifacts/managed_poc_smoke_last_run.json`）。  
> 2026-08-05 **CG-PAY 落地（程式層）**：NewebPay MPG checkout＋notify webhook；`billing_records` 表；付款成功 `apply_plan_quota`；未設 `NEWEBPAY_MERCHANT_ID` 時 checkout fail-closed 503；E2E 實測待商戶憑證。  
> 2026-08-05 **WS-SECURITY 三層限流**：production/staging 啟用 IP＋user＋tenant Redis 滑窗；chat 路徑另限 `RATE_LIMIT_CHAT_PER_USER`；webhook／login 白名單。  
> 2026-08-05 **CG-STORAGE 遷移腳本**：`scripts/migrate_storage_local_to_s3.py`（dry-run／execute；雲端帳號實測待辦）。  
> 2026-08-05 **WS-QA-CLOUD 發布閘門**：`scripts/cloud_release_gate.py`（安全掃描＋答題 artifact 新鮮度＋託管 health smoke）。  
> 2026-08-05 **Bugbot 8 findings 修補**：token 預留估算、payment 單一 transaction＋失敗回 500、chat 配額延後至對話驗證後、儲存 FOR UPDATE、SSO redirect_uri 釘選、p7 RLS 補表、移除 debug Celery tasks。  
> 2026-08-05 **CG-PAY 模擬 E2E**：`scripts/e2e_payment_newebpay.py`（checkout→加密 notify→升等＋billing 冪等；真實藍新仍待商戶憑證）。  
> 2026-08-05 **WS-GTM／DATA／AGENTIC**：`SAAS_TENANT_ONBOARDING.md`、`DATA_DELETION_AND_EXPORT.md`、`docs/legal/DPA_TEMPLATE.md`（草稿）、`scripts/provision_managed_instance.py`（開通骨架＋確認交付閘門）。  
 
> 2026-08-03：FOUNDATION F0–F4 **全部完成並驗證**；FD-* 五閘門 PASS。  
> VISION Point A→B：約 **75–85%**（Blind Z3 67/85；Blind Z4 39/50；Z2 27/27 不得單獨當 Point B；見 `VISION_POINT_A_TO_B.md`／`artifacts/blind_z*/BASELINE_TRIAGE.md`）。

> **✅ CV-INT 已 PASS（2026-08-02 重跑）**：B1 正式 KB 切換 DeepDOC + B2 重解析後，動態查核 0 違規（正式 KB `layout_recognize=DeepDOC`，7 份宣稱 deepdoc 的文件與上游一致）。靜態掃描仍為 0；`tests/test_label_integrity_gate.py` 防回歸。
>
> 仍開放的能力閘門見 `CAPABILITY_ACTIVATION_AND_VALUE_PROOF_PLAN.md` §7。  
> 2026-08-02 更新：能力啟用計畫可自動項已跑完。C2 LOCAL_FS **BLOCKED**；CV-RF-02／04／PH-05／WK-05 價值 **NO_VALUE**（WK-05 接線 PASS）；進階能力預設 OFF。  
> 剩餘僅人工閘門：外部滲透／法律／DR；SP／Drive OAuth 本機 SKIP。
>
> ```bash
> python scripts/eval_label_integrity.py     # 需 POSTGRES_* 與 RAGFLOW_* 環境變數
> ```

**施工約定**：目標為整份計畫完成時，代理人應連續推進；不要分段詢問是否繼續。  
僅在需要使用者提供外部憑證／簽核時中斷。

```bash
python scripts/plan_progress_gate.py --write-md --strict
```

## MKA（製造業知識助理）狀態

> 2026-08-06 **願景補齊驗證**：`mka_progress_gate.py --all` → **28/28 PASS**；migration head=`mka_p2_vision_platform_001`；執行中 API `:8005` OpenAPI 已含 scene registry／job-roles／templates／enterprise／metrics／interview。
> 本輪可程式項：SceneRegistry 正式 migration＋管理 API；Scene→表單預填／聊天檢索；JobRole 指派＋五正式模組 DB 路由；動態 JobHome；公司 DOCX/XLSX 版型；表單 instance 清單／詳情；訪談建卡；真 Document SOP 衝突；ERP/CRM/MES fail-closed adapter＋DB write guardrail；MKA 事件指標；刪除死代碼 `pages/quote|incident`。詳見 `docs/MKA_FEATURE_INVENTORY.md` §9 驗收矩陣。

| 類別 | 項目 | 狀態 |
|------|------|------|
| 程式 | MKA 願景平台＋28 gates（含 runtime OpenAPI） | ✅ 已驗證（2026-08-06） |
| 程式 | 動態職能工作台／模組管理／表單歷程／訪談 UI | ✅ 已驗證（2026-08-06） |
| 不可代勞 | 真實客戶 DOCX／XLSX 版型比對驗收 | ❌ 需客戶檔案 |
| 不可代勞 | ERP／MES 真實規格與憑證 | ❌ 外部 gate |
| 不可代勞 | 三角色 UX 研究／任務測試（MKA-UX-*） | ❌ 需真人訪談 |
| 不可代勞 | 真機＋弱網＋噪音 E2E | ❌ 需真實手機 |
| 不可代勞 | Design Partner UAT | ❌ 需真實客戶 |
| 不可代勞 | Cloud pentest／法律簽核 | ❌ 同下方人工閘門 |

```bash
python scripts/mka_progress_gate.py --all   # MKA 獨立閘門（不混入主計畫統計）
```

## 目前狀態（自動閘門）

- 計畫 checkbox：**47/48**
- 可驗證 code：**100% (32/32)**
- false_green：**0**
- 內部工程 Gate：**0 個阻擋項**
- 外部商業化追蹤：滲透、法律與客戶 DR；不計入開發完成率
- 本機階段 SKIP：SharePoint / Google Drive OAuth

## 真治本閘門（FD-*，架構契約）

| ID | 項目 | 狀態 | 計畫／ADR | 完成判準（防假綠） |
|----|------|------|-----------|-------------------|
| FD-DELIVER | 掃描／OCR 入庫交付不變量 | **✅ PASS（2026-08-03 重跑）** | ADR-010、F1 | 無 completed∧text_fallback；缺依賴必 failed |
| FD-CATALOG | Catalog＋Chunk 多粒度契約 | **✅ PASS（2026-08-03）** | ADR-008、F2 | 盤點題走文件層；關題號特判仍過 |
| FD-FUSION | Gateway 融合不變量 | **✅ PASS（2026-08-03）** | ADR-009、F3 | 無檔名 compiled 不得擠掉內部 document；禁靠關源過關 |
| FD-QUERYPLAN | QueryPlan 結構化意圖 | **✅ PASS（2026-08-03）** | FOUNDATION F4 | intent／arms／sub_queries；複合盤點 multi_hop |
| FD-CLAUSE | 跨語條款對照投影 | **✅ PASS（2026-08-03）** | FOUNDATION F4 | DB 投影＋Wiki 同步＋translate chat；R19 pass |
| VISION-ADV | 對抗集 | **✅ PASS（8/8）** | VISION Phase 4 | 檔名誤導／拒答／跨檔期間／多語 |
| VISION-CEILING | 能力上限就位 | **✅ PASS** | VISION Phase 5 | rerank／Phase2 模組／條款投影 |
| ANSWER-40 | 主黃金集 40 題 | **✅ 40/40 pass** | VISION Phase 4 | `answer_correctness_last_run.json` |

> FOUNDATION＋VISION 核心可重跑：`make foundation-gates`；另跑 `eval_adversarial_gate.py`／`eval_answer_correctness.py`／`eval_capability_ceiling.py`。

詳見：`docs/FOUNDATION_RETRIEVAL_AND_DELIVERY_PLAN.md` §0.3／§5。

## 不可代勞（需外部人／客戶／憑證）

| ID | 項目 | 計畫勾選 | 為何無法純程式關閉 | 證據位址 |
|----|------|----------|-------------------|----------|
| HG-PENTEST | 外部滲透測試 | `[ ]` | 需獨立第三方／授權範圍 | `FINDINGS_REGISTER` → 完成後加 `SEC-PENTEST-*` |
| HG-OAUTH-SP | SharePoint Online 連接器 | **SKIP（本機階段）** | 本機開發先跳過；不阻斷閉環 | `DEV_OAUTH_SETUP.md`（日後恢復） |
| HG-OAUTH-GD | Google Drive 連接器 | **SKIP（本機階段）** | 同上 | 同上 |
| HG-LEGAL | 模型／依賴商用授權審查 | 計畫註記人工 | 法律／採購簽核 | `FINDINGS_REGISTER` |
| HG-DR-SIGN | 客戶現場 DR／安裝簽核 | 計畫註記人工 | 客戶環境演練簽名 | `artifacts/ops/*` |

> **2026-08-01**：本機階段跳過 SP／Drive OAuth；第一批連接器以 `nas_smb` 為準。  
> **唯一仍未勾的出口條件 checkbox**：外部滲透測試。  
> **DD P0／P1**：已完成（pytest 277+）。  
> **P2 進度**：…；code-review 修復：資源級 deny、watcher review 清舊索引、SSO tenant filter、deploy stop→migrate→up、憑證 Fernet 加密。  
> 外部商業化追蹤：外部滲透／法律／DR；與工程完成判定分開。

## 已可由自動化關閉（本輪已關）

| 項目 | 腳本 | Artifact |
|------|------|----------|
| Critical/High 依賴+SAST+API smoke | `security_findings_gate.py` | `security_scan_last_run.json`（open_CH=0） |
| Pilot RAGFlow E2E | `e2e_vertical_slice_full.py` | `pilot_e2e_last_run.json` |
| Retrieval Hit@K + ACL | `eval_retrieval_gate.py` | `retrieval_gate_last_run.json` |
| Wiki/Graph + live WeKnora | `eval_wiki_graph_quality.py` | `wiki_graph_eval_last_run.json` |
| Backup | `ops_lifecycle.py backup` | `artifacts/ops/backup_*.json` + `backups/` |

## 關閉滲透閘門的條件

1. 取得第三方滲透報告
2. 在 `docs/security/FINDINGS_REGISTER.md` 新增 `SEC-PENTEST-*`（closed 或 open 分列）
3. 將計畫 GA「外部滲透測試完成」勾選
4. 重跑 `plan_progress_gate.py --write-md --strict` → checkbox 48/48
