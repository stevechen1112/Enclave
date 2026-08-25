# Gate 2 — Demo 隔離、文件可見性與唯一可回答狀態

日期：2026-08-25  
狀態：**PASS**

## 完成項目

### 1. Demo 登入改為 fail-closed

- `DEMO_LOGIN_ENABLED` 預設仍為 `false`。
- 啟用時必須設定明確的 `DEMO_TENANT_ID` UUID；缺漏或格式錯誤會拒絕啟動。
- `tenants` 新增 `is_demo`，只有 `is_demo=true`、狀態 active 且 UUID 完全相符的租戶能核發免密碼 Demo token。
- 六個 persona 只能解析到該 Demo tenant 內的固定帳號與指定 security/job role。
- 移除 Demo admin 找不到時自動選取同租戶任意 owner/superuser 的 fallback。
- Demo admin 改為保留網域下的內部 door identity，不再指向正式站擁有者帳號，也不作為人工登入名稱。
- migration head：`demo_tenant_boundary_k6_006`；離線 SQL 已確認會新增 non-null 欄位與索引。

這一關只建立不可跨越的安全邊界；合成 Demo tenant、資料、六角色與重置機制在 Gate 4 建立。正式站目前仍維持 Demo login 關閉。

### 2. 文件列表與詳情共用檢索 PEP

`GET /documents/` 與 `GET /documents/{id}` 現在共用：

- tenant 必須完全相符，superuser 也不會用文件 ID 跨 tenant 讀取。
- tombstone deny-first。
- 部門範圍與祖先部門規則。
- connector source-record allow ACL 與 deny precedence。
- 非管理角色只能看到自己可存取的 active KB revision 成員。
- 非管理角色看不到只完成上傳、尚未正式發布的文件；詳情一律回 404，避免洩漏存在性。

### 3. 唯一 `answer_ready` 契約

新增 `app/services/document_readiness.py` 作為 API、管理總覽與檢索臂的共同事實來源。可回答必須同時符合：

1. 文件未撤銷。
2. 成員屬於 active knowledge base 的 active revision，且 revision 等於 KB 的 `active_revision`。
3. 使用者有該 KB revision 的存取權。
4. 對應 revision 的 `DocumentProfile.answer_ready=true`。
5. 對應 revision 至少有一個 chunk。
6. 若正式 revision 就是文件目前 revision，`Document.status` 必須是 completed；若正在處理較新版本，已發布舊 revision 可繼續服務。

沒有 active revision 時，scope 現在明確為空並 fail-closed，不再回退到「completed 文件直接搜尋」的 legacy 路徑。

此契約已套用到：

- 文件 list/detail API 與 knowledge-control overview/documents。
- canonical chunk / hybrid retrieval。
- catalog 與 filename-token arm。
- structured table / procedure projection。
- clause projection。
- document-head 補強。
- PageIndex artifact。
- sidecar/gateway 回傳的第二次 canonical revalidation。

### 4. 前台狀態與用詞

- `completed` 不再直接顯示「可搜尋」，沒有 canonical readiness 時顯示「尚不可查」。
- 文件詳情顯示正式發布 revision 與正式可查 chunk 數，不再用 mutable `document.chunk_count` 冒充已發布內容。
- 「目前能否被問到」與「測試提問」按鈕直接依 backend `answer_ready`。
- 總覽的「員工可查文件」只計算 canonical ready 文件。
- 總覽會列出處理完成但缺品質、chunks 或正式發布的文件，不再顯示「目前一切正常」。
- 健康文案移除「員工問什麼都能找到答案」的過度承諾，改為說明完整回答、部分回答與查無證據皆屬正常受控結果。

### 5. SOURCE_VERIFY_MODE

- 設定載入時會先 `strip().lower()`。
- 只允許 `off`、`shadow`、`enforce`；其他值拒絕啟動。
- orchestrator 執行時再做一次防禦性 trim，避免測試或 runtime mutation 重新帶入尾端空白。

## Code review 修正紀錄

本關初版完成後，review 額外發現並修正：

1. 只修前台與文件 API 仍不足，catalog、structured/procedure、PageIndex 與 sidecar hit 可繞過 profile readiness；已把同一契約下壓至所有主要檢索臂。
2. 既有 `resolve_kb_revision_scope` 在 tenant 沒有 active revision 時會省略 scope，導致 retriever 回到 current-document legacy 搜尋；已改為明確空 scope、全臂拒絕。
3. 使用者可看到 active revision，但未必是該 KB 的 member；文件 list/detail 現在使用和問答相同的 KB membership scope。
4. 文件可能在多個 KB 內；readiness 會選擇任一真正可用的正式 revision，而不是被較高但壞掉的 revision 覆蓋。
5. 新版處理失敗不能讓舊正式版下線；契約已明確允許 `published_revision < document.version` 的舊版繼續服務。
6. frontend `Document` 型別縮排錯誤在 review 中修正，TypeScript build 再次通過。

## 驗證證據

- 擴大後端回歸：172/172 PASS（Demo、documents、permissions、tenant isolation、readiness、knowledge control、QueryPlan、retrieval、catalog、clause、gateway、source verifier 等）。
- 另一次針對 knowledge control / scope / orchestration：42/42 PASS。
- 前端：47/47 PASS；ESLint PASS；TypeScript + production build PASS。
- 新增 Python 檔案 Ruff：PASS；所有變更 Python 檔案 critical E9/F 檢查中只有既有未使用 import 債務，沒有新語法或 undefined-name 錯誤。
- `git diff --check`：PASS。
- Python compile：PASS。
- Alembic：單一 head `demo_tenant_boundary_k6_006`；migration offline SQL PASS。
- 測試警告 7 筆均來自第三方 `jieba/pkg_resources/pyannote` deprecation，非本關功能失敗。
