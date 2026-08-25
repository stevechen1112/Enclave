# Enclave 知識庫提升施工與 Code Review 報告

日期：2026-08-25  
依據：`ENCLAVE_ENTERPRISE_KNOWLEDGE_BASE_ENHANCEMENT_PLAN.md` 1.1  
結論：核心功能與發布防線已施工；目前不得發布或宣稱對外測試完成，因獨立驗收與正式環境證據尚未齊備。

## 已完成的產品實作

| 階段 | 已完成內容 | 程式驗證 |
|---|---|---|
| K0 | 能力處置矩陣、corpus/eval 邊界、核心題句洩漏掃描、穩定 citation revision、正式環境唯讀基線 | 正式 backend image、runtime prompt/config、24 documents／132 chunks 與 ACL/corpus digest 已凍結且不含敏感本文；獨立 Z5 尚待 custodian 建立 |
| K1 | DocumentProfile、格式/能力 readiness、Canonical Knowledge Unit、表格/程序/know-how projection、ingestion/backfill | ingestion 與 profile 測試 |
| K2 | immutable KB membership、document revision 隔離、candidate/shadow/active、runtime release、rollback audit、K1/K2 migration | K1/K2 migration 與後續 K3–K5 相容升級至 `runtime_binding_k5_005 (head)` |
| K3 | QuerySpec 欄位、AnswerSlot、EvidenceContract、slot coverage、ambiguity/risk | query/coverage/validator 測試 |
| K4 | 同列結構化取值、數字/日期型別、aggregate lineage、租戶核准 entity alias、procedure branch/completion | 不跨列、列識別、程序分支與拒答測試 |
| K5 | structured/procedure 正式接入 multi-arm 問答；tenant/department/source ACL、deny-set、KB revision、權威與 know-how scope | ACL/revision/knowledge tests |
| K6 | immutable evaluation run、first-run 保留、Wilson interval、domain/slot 分母、兩組 sealed holdout 發布閘門 | evaluator 測試；真實兩組 sealed first-run 尚缺 |
| K7 | 持久化 lexical index、增量更新、精確 chunk 級容量抽樣、read-only profiling | lexical 測試；真實 1k/10k/100k profile 尚缺 |
| K8 | 知識控制中心、readiness、回饋與保鮮 UI、列/頁/工作表來源欄位、六 persona 驗收證據 validator | 前端 lint/unit/build PASS；最終候選映像的六 persona 開發者預驗收 PASS，獨立瀏覽器矩陣仍尚缺 |
| K9 | process-wide DB read-only Shadow、前後 digest、exact revision/manifest/runtime 綁定、promotion/rollback | Shadow 工具與 release tests；正式 tenant Shadow 尚缺 |
| K10 | 回饋 owner/status/history、freshness scan、gap/evaluation 模型與管理 UI | feedback/freshness tests |

## 第二輪 Code Review 修復

1. 修正 secondary retrieval arms 可繞過 KB membership、department/source ACL 或 exact document revision 的風險。
2. 修正相同檔名跨部門的 document-head 洩漏。
3. 修正 active revision 在 live document re-index 時因狀態暫變而不可讀；immutable revision 仍可讀，tombstone/revoke 仍立即生效。
4. structured/procedure projection 原先只建索引、未接入問答；現已成為正式檢索臂。
5. 修正不同表格列的金額/日期可能由 narrative fallback 重新拼湊；canonical ambiguity 現在會覆蓋 narrative 並拒答。
6. 修正一列同時有編號與名稱時必須全部出現在問題才命中的過度拒答；任一唯一識別值即可選列，多列仍拒答。
7. 程序有未確認條件或流程名稱不唯一時，禁止模型自行選分支；安全程序直接 abstain。
8. 修正 feedback API 可對其他租戶/使用者訊息送回饋的污染風險。
9. 修正一般租戶成員可讀 knowledge-control revision membership metadata；現限管理員。
10. 修正 promotion 只保存 KB release、未綁 runtime release，以及 rollback 未同步 runtime/audit actor。
11. 所有 13 個發布閘門現必須由同一個最終 `sha256:<64 hex>` 映像產生；跨映像證據一律拒絕發布。
12. 瀏覽器不能自行提交 PASS；KB-UX-01 只接受獨立 QA/產品負責人/外部測試者的逐案例證據。
13. 修正容量工具以文件數假裝 chunk 數的量測錯誤。
14. 補齊前端既有 16 個 lint errors、型別錯誤及 freshness 操作失敗提示。
15. K1 新知識表原先只有應用層 tenant filter；現已為 16 張 tenant-owned 表建立 fail-closed PostgreSQL RLS，K2 亦會替早期 K1 安裝補建 policy。
16. 修正 Alembic inspector 在 SQLAlchemy 2 自動開啟交易，導致 migration 顯示成功卻於連線關閉時回滾；現在先結束唯讀盤點交易，fresh upgrade 會真正提交。
17. `alembic check` 原本把歷史索引名稱差異誤判成 drop/create，且可能誤刪 partial unique；現以 columns／unique／predicate／NULLS NOT DISTINCT 語意比較，真正差異由 `schema_norm_k3_003` 修正。
18. sealed 評測原可用少量案例或同 corpus 換題目假裝兩輪；現要求每輪至少 200 案例、四領域各 50、20% mixed-language/縮寫/料號、hash-bound 獨立 seal，兩輪 corpus 與 question hash 均不同。
19. 容量 gate 原只順序跑少量字串查詢且無品質/尾延遲/資源門檻；現按 Lite／Team／Enterprise 必要 chunk 階梯與最低併發量測 P50/P95/P99、hit@10、錯誤、scope violation、CPU/記憶體/儲存/成本觀測，禁止縮小 size 或降低 baseline 門檻。
20. Production Shadow 原用 superuser 繞過 ACL 且一題即可 PASS；現要求至少 30 個真實 subject/role/department 案例、至少四個 deny/forbidden 負例與兩個 subject，全程 process-wide read-only。
21. 瀏覽器 pairwise 原只需任一兩欄案例；現要求五個授權維度的 10 組 pair 全覆蓋，所有 persona/negative/surface PASS 需附 traceable evidence refs 與獨立 runner attestation。
22. `KB-OPS-01` 原可由單元測試直接簽發 PASS；現已自一般 contract runner 移除，必須另驗證 feedback owner/status/history、100% active 文件 freshness、撤權/過期/connector 失效負例、trace 隱私、backup/restore/rollback 與 RTO operator evidence。
23. 修正 backend Docker context 會把 artifacts、盲測語料、測試資料、Makefile、舊 compose、monitoring、mobile 與工作區雜項一併複製進映像的風險；`.dockerignore` 現採 runtime allowlist，並以 exact-file deployment manifest 凍結實際部署輸入。最終 `/code` 根目錄只含 `.dockerignore`、Dockerfile、alembic.ini、app、celery_worker.py、configs、docker、requirements.txt。
24. 修正 frontend builder 的 Node 20 與相依套件 Node 22 engine 不相容，以及 lockfile 內 `nanoid` 高風險版本；builder 改為 Node 22，lockfile 更新後 `npm audit --omit=dev` 為 0 vulnerability。
25. 修正 runtime profile 的「no DB」解析在 DB 尚未 ready 時仍會於模組匯入直接崩潰；現在只對 SQLAlchemy DB failure 使用明確 `nogpu` fail-safe，程式邏輯錯誤仍會向外拋出。
26. 修正歷史環境曾由 ORM `create_all` 先建表、但 Alembic stamp 落後時，P6/P7/K1 migration 直接撞表失敗；現在只承接欄位完整的既有表、補齊 index/RLS，partial schema 則 fail closed。舊資料庫 clone 與 fresh DB 均已升級至 head。
27. 修正第六道門把管理員綁死在 `admin@kachu.tw`，導致實際 demo tenant 使用其他 owner 帳號時無法登入；現在先取可設定的首選管理員，缺席時只在同一 demo tenant 內選擇 active owner+superuser，且仍受 demo read-only middleware 保護。
28. 修正 `master@demo.mka` 被錯配成主管職能、看到過寬現場選單；新增正式 `master` 職能、最小模組集合與 K4 migration，畫面現顯示「班長／師傅」，不再顯示報價功能。
29. 修正長訪談雖已有 `/knowhow/interview`，但「師傅經驗」主要操作仍只會建立空白舊卡片而無法抵達錄音頁；現改為「開始師傅訪談」主操作，並保留「手動建立經驗卡」次操作。
30. correctness lint 找到 `task_engine.py` 的 `TaskRun` 型別註記未宣告；以 `TYPE_CHECKING` 明確匯入後，全 repo 的致命/未定義名稱檢查與 51 項任務引擎回歸均通過。
31. 第三輪發布 code review 發現瀏覽器驗收只綁 backend image，理論上可用舊 frontend 搭配新 backend 產生 UI 證據；現要求 `KB-UX-01`、Shadow runtime manifest 與 promotion 三處同時核對 backend digest、frontend digest 與 `deployment_manifest_id`，任一不一致即 fail closed。
32. 新增 `prepare_knowledge_acceptance_handoff.py`，以 exact tenant/revision/KB manifest/deployment images 產生獨立驗收交接包；所有模板預設 `NOT_RUN`／`PREPARED_NOT_ATTESTED`、拒絕覆寫既有證據，也不建立 custodian/QA/operator attestation。
33. 修正 promotion 雖會檢查 frontend/deployment 綁定、但 `RuntimeRelease` 稽核紀錄只永久保存 backend digest 的缺口；K5 migration 新增向後相容 nullable 欄位，新發布會保存 `frontend_image_digest` 與 `deployment_manifest_id`，既有發布不偽造未知值。
34. 將 correctness lint 擴至全部 `scripts` 後，修正 `ops_lifecycle` 兩個未宣告 tarfile 型別、`test_data_factory` 未初始化的區域計數器，以及 `test_flow5_bulk_agent` 將 `ok()` 遮蔽成字串的錯誤；app/scripts/tests 的致命與未定義名稱檢查現全數通過。
35. 修正 `deployment_manifest_id` 原本只由原始檔案決定、沒有納入實際 build image ID 的供應鏈綁定缺口；現由 exact deployment files、backend image ID 與 frontend image ID 共同計算，同檔案重新建出不同映像時 manifest ID 必定改變。
36. 修正 `KB-BL-01` 把歷史正式基準映像誤填為本次候選證據映像的版本綁定錯誤；現在保留 `baseline_source_image_digest` 供基準追溯，gate 的 `image_digest` 則必須由 CLI 明確綁定本次候選，避免後續 same-image promotion 永遠無法成立。
37. 新增不可變交接包完整性驗證與外部驗收統一執行器；前者逐檔核對 SHA-256、tenant/revision/KB manifest/backend/frontend/deployment 綁定，後者只消費交接包外的獨立證據並依序執行六個 gate。空白模板的 fail-closed 反向測試已通過，工具不 promotion、不自行簽證，也不把完整性 PASS 冒充驗收 PASS。
38. 修正外部 custodian 的 Z5 seal 只能放在專案固定路徑的隱含依賴；`KB-BL-01` 與統一執行器現在可明確接收 `--z5-seal`，預檢會要求至少 200 案例、四領域與 custodian 身分，再由 gate 核對 attestation SHA-256。

## 已執行驗證

- Python compile：PASS。
- 核心題句/客戶特例洩漏掃描：PASS。
- Knowledge plan gate：104/104 PASS，最終 artifact 已重建。
- 針對 K1–K5/release 的測試：41/41 PASS。
- 前端 ESLint：0 errors。
- 前端 Vitest：11 files、44 tests PASS。
- 前端 production build：PASS。
- PostgreSQL fresh install：base → `runtime_binding_k5_005 (head)` PASS。
- PostgreSQL tenant RLS：16/16 新知識表已啟用，16/16 tenant_isolation policies 存在。
- 完整後端最終主回歸（隔離、全新驗收 DB）：1043/1043 PASS；僅 7 個外部套件 deprecation warnings。
- `git diff --check`：PASS（新增 `.gitattributes`，確保 PDF fixture 以 binary diff 處理）。
- 早期 K1 相容模擬：移除 16 個 RLS policies 後升級 K2，16/16 RLS 與 16/16 policies 全數恢復。
- 正式環境 K0 唯讀凍結：backend image `sha256:5f0b…2fb0`、`production_corpus_manifest_id=pcm-c44a76b497a92b050402da89`，正式交易確認 `transaction_read_only=true`。
- Alembic schema normalization：fresh base 與舊 P5 clone 均升至 `runtime_binding_k5_005 (head)` PASS；`alembic check` 無新增操作；K3 downgrade → upgrade → check 往返 PASS。
- 本輪新增 gate/migration/acceptance 單測：26/26 PASS；app/scripts/tests 全範圍 Ruff correctness profile（`E9,F63,F7,F82`）PASS；Python compileall PASS。完整 Ruff default 規則仍有約四千筆既有風格／現代化／廣泛例外等技術債，未以大量機械改寫混入本次候選版。
- 前端供應鏈：Node 22 image build PASS；`npm audit --omit=dev` 0 vulnerability。
- 最終候選瀏覽器預驗收：同一份最終映像六 persona 均可由六道門登入並登出；業務／現場／師傅／新人／唯讀進入 `/job`，管理員進入 `/overview`；師傅最小權限與長訪談入口 PASS。390×844 無橫向溢出、console 0 error/warning。此為開發者證據，不冒充獨立 `KB-UX-01`。
- 獨立驗收交接包：隔離 clone 已建立 141 members 的 shadow revision `ab1ecdff-3b1a-4e36-9b63-5fbdb6f0ace4`，最終交接包綁定 KB manifest `42e352…cbfde` 與最終 deployment/images；逐檔完整性為 `INTEGRITY_PASS_NOT_ATTESTED`，模板仍全部為 `NOT_RUN`／`PREPARED_NOT_ATTESTED`，不計 release PASS。
- 部署輸入凍結：`deployment_manifest_id=dm-1d055ad44987fddf5f8d8e5d`，474 個明確輸入（backend 331／frontend 130／gateway 13）；目前 258 筆 workspace dirty 狀態不會再被無差別打包，候選輸入 120、排除規則命中 190。ID 現同時綁定 exact files 與實際 backend/frontend image IDs；計數反映 path 規則命中，部署內容仍以 474 個 exact file records 為準。
- 候選映像：backend `sha256:40566798732ad45c24aa61753dc87fdc2ca429d8bb5d8ef26f0f742dc4ece54f`；frontend `sha256:911b5756461ef8f8941f4f1d076e0dbc787357312229aec6c048eb210e1dc2c6`。映像內容檢查確認不含 artifacts、盲測語料、tests、docs、scripts 或 `.git`。

## 尚未解除的發布阻斷

| 阻斷 | 原因 | 解除方式 |
|---|---|---|
| KB-BL-01 | 正式映像/corpus 基線與 Z3/Z4 hash freeze 已完成；但 K0 要求的全新 Z5 尚未由獨立 custodian 建立與封存 | 獨立保管者用至少 200 案例、每領域 50、20% 混合語言/料號案例建立新 corpus/questions，附 attestation 並產生 seal |
| KB-EVAL-01 | 缺兩組不同 corpus/question 的 sealed first-run | 由未參與修題者建立、密封並執行兩組 holdout |
| KB-SCALE-01 | 現有正式 corpus 未達宣稱的 1k/10k/100k chunks | 依部署 profile 準備合規合成/實際容量資料並量測 |
| KB-UX-01 | 缺六 persona、pairwise 權限、手機/錯誤/來源卡的獨立瀏覽器證據 | QA/產品負責人用最終映像完整走查並送入 validator |
| KB-SHADOW-01 | 尚未在正式 tenant 用最終映像執行 read-only Shadow | 由正式環境 operator 執行 Shadow 與 mutation sentinel |
| KB-OPS-01 | 最終映像的 feedback/freshness/trace privacy 與 backup/restore/rollback RTO 尚無 operator 證據 | 在 staging/production-like 環境演練，以同 revision/manifest/image 送入獨立 OPS validator |

上述項目需要獨立測試者、真實資料規模或正式環境權限；開發者不能以自行撰寫 PASS JSON 取代。發布 API 會在 13 個 exact-revision、exact-manifest、same-image 閘門未全數通過時拒絕 promotion。
