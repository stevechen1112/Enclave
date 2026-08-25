# Gate 6 — Migration、完整回歸、六角色瀏覽器驗收與 Code Review

日期：2026-08-25  
結論：**PASS**（僅放行進入 Gate 7；尚未部署正式站，也不代表 GA）

## Migration 與資料保護

- 在隔離的本機候選資料庫執行完整 Alembic migration，結果為
  `demo_tenant_boundary_k6_006 (head)`。
- migration 前建立 PostgreSQL custom-format 備份：
  `artifacts/release/enclave_gate6_pre_migration.dump`（Git 忽略）。
- 備份 SHA-256：
  `5AE60716EB2EB099FDDD97E9C4273F1B3C51D80FC2415FBF0866C471782628F1`。
- 瀏覽器驗收後執行 canonical Demo transactional reset，刪除 94 筆驗收產生資料；
  reset 與其後獨立 verify 均為 `ok=true`。
- 最終 Demo 不變量全部通過：6 位非 superuser 人物、5 份 synthetic 文件、5 個
  answer-ready chunks、唯一正式 KB revision、完整職能／模組／表單／QR scene、無
  connector、無 sidecar binding、無 SSO secrets。

## 完整自動化證據

- 後端收集：1,095 tests。
- 後端最終完整執行：**1,095 passed、0 failed、0 skipped**，307.36 秒。
- 7 個 warning 均來自 `jieba/pkg_resources/pyannote` 第三方棄用通知；沒有產品測試
  warning 或 skip。
- 前端：14 test files、**57/57 passed**。
- 前端 ESLint：PASS。
- TypeScript + Vite production build：PASS（3,331 modules transformed）。
- Python `compileall`：PASS。
- 本關變更 Python 的阻斷級 Ruff（E9、F63、F7、F82）：PASS。
- `git diff --check`：PASS。
- 追蹤與本關 dirty/untracked 共 1,539 個來源檔的高可信度秘密掃描：0 findings。

## 真實瀏覽器流程

候選前後端僅綁定 localhost `127.0.0.1:18012/18011`；以真實瀏覽器完成：

1. 產品介紹首頁與六道門：六位人物、角色說明、合成資料警語、免密碼進入均正常。
2. 業務：登入 → 全部工作入口 → 中文自然語句建立報價 → 欄位核對 → 送審 →
   管理者核准 → 回原單確認已核准 → Word/Excel/PDF 三種匯出。
3. 設備現場：登入 → 全部工作入口 → 填寫設備維修紀錄 → 檢查 → 送審 → 管理者
   核准 →「我的表單」找到已核准單 → Word/Excel/PDF 三種匯出。
4. 班長／師傅：登入 → 訪談頁 consent、分段保存、60 分鐘上限、逐字稿與草稿控制
   檢視 → 手動建立經驗卡 → 編輯 → SOP 衝突檢查 → 送審 → 管理者核准 → 已核准
   經驗卡可見。
5. 新人：只能查看與執行新人工作入口；不能進訪談、建立、編輯、送審或下架師傅
   經驗。直接輸入訪談 URL 亦被導回列表。
6. 主管檢視：只顯示查看合成知識、查看已核准師傅經驗與問答；文件清單精確為 5
   份 synthetic 文件，沒有客戶／候選環境資料。
7. 公司管理：總覽顯示 5 份可搜尋、0 份失敗；待審內容以中文欄名呈現；完成師傅
   經驗、報價與設備維修核准；Demo 模組變更按鈕停用且有明確提示。
8. 六角色切換與登出反覆驗證正常，管理者核准收件匣最終為空。
9. 390×844 手機 viewport 實測產品首頁、六道門、側邊選單、登出、工作台、核准文件
   與匯出按鈕；無橫向溢位、遮擋或不可操作控制，驗收後已還原 viewport。
10. 候選後端與 nginx 記錄未發現 500/502/503/504、ERROR 或 traceback。

實體麥克風錄音、相機 QR 與 OpenAI Realtime 在此候選組態刻意關閉；其程式契約與
錯誤降級由自動化測試覆蓋，實際音訊品質與長時間錄音壓力屬後續容量／正式 Shadow
關卡，不能以本關瀏覽器證據宣稱已完成。

## 本關發現並修正

1. Demo 可開六道門但表單與師傅經驗旗標可能未開：啟動時改為 fail closed，要求
   Fixed Form、Know-how 與 Module Router 完整能力組。
2. 新人與主管唯讀可從 URL 進入師傅訪談或修改草稿：新增 API 級 master/admin
   author boundary，前端按鈕與 route guard 同步。
3. 「幫合成示範客戶報價」被解析成客戶「報價」：修正中文動詞框架與欄位覆寫。
4. 兩句「不得／不可」安全禁令被誤判互斥：比對前移除完整禁止詞，避免「得／可」
   子字串造成假衝突；真衝突以結構化 409 與中文差異卡呈現。
5. 管理者待審畫面顯示英文欄位與技術識別碼：改用 fail-closed 中文白名單。
6. 核准後完整表單顯示 `quote/approved`、英文鍵、UUID 與整段 JSON：改成中文表單、
   中文狀態與中文欄位，內部 provenance 只提示已保存供稽核。
7. 現場表單核准後，工作台因待處理數為 0 而沒有入口可找回：新增固定「我的表單」
   入口，已核准頁可預覽與匯出。
8. Demo 系統模組按鈕看似可修改但 API 會阻擋：前端明確標示展示模式並停用控制。
9. Viewer 無職能時誤顯示「尚未指派職能」：改成明確唯讀工作區與三個可用入口。
10. 完整測試的設定案例會受先前 `load_dotenv` 污染：測試改成顯式指定缺失能力。
11. 重複跑完整套件時，Redis abuse counter 跨程序累積導致大量 429：整合 fixture
    關閉共用 IP 限流；限流行為仍由獨立單元測試驗證，完整套件可重複執行。

## Code Review 結論

- 權限由後端 dependency 強制，不依賴隱藏按鈕；讀取、作者、核准／下架三層分離。
- Demo 模式只由 canonical UUID 加上 `tenants.is_demo=true` 判定，不能由租戶名稱或
  request 參數偽造。
- 表單與審核 UI 對未知欄位 fail closed，不會因後端新增 metadata 就直接曝光。
- Demo reset 僅接受固定 UUID 且拒絕未標記 synthetic 的租戶；本關使用精確確認值。
- 變更中未發現未處理的 P0/P1/P2 review finding。
- 全專案 Ruff 既有 5,434 項歷史債仍然存在；本關未以大規模機械修復擴張風險，
  只宣稱本關阻斷規則通過。

## 放行限制

Gate 6 只證明 migration、完整回歸、合成 Demo、角色流程與瀏覽器 UI 可進下一關。
Gate 7 的兩套全新 sealed Z5（每套至少 200 題）尚未執行；容量、正式 Shadow、備份
還原演練、回滾、外部滲透與正式部署亦尚未完成，因此正式站維持原狀。
