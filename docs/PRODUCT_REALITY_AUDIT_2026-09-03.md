---
title: "Enclave 全產品 Product Reality Audit"
document_type: "product_reality_audit_plan"
language: "zh-TW"
version: "1.1"
date: "2026-09-03"
status: "READY TO EXECUTE — AUDIT NOT YET COMPLETE"
owner: "Product Owner"
scope: "Enclave 全產品、正式環境、核心能力、應用模組、外部依賴與營運交付"
---

# Enclave 全產品 Product Reality Audit

## 0. 文件結論

這份文件建立 Enclave 的全產品真實性稽核制度。它不是另一份「功能已完成清單」，也不會因為程式存在、單元測試通過、頁面打得開或服務回傳健康，就判定產品已經可交付。

本次稽核只回答一個問題：

> 一位不知道系統內部設計、使用真實帳號、真實設備、真實網路與真實工作資料的企業使用者，能否在沒有工程師陪同修改資料庫或臨時救援的情況下，安全、清楚、可重複地完成工作，並取得可信且可追溯的結果？

截至 2026-09-03，Enclave 的正確對外狀態應表述為：

- 核心架構、Input、Knowledge、Ask、模組化與多項正式環境技術驗證已具備相當基礎。
- 八策股份有限公司第一輪真實測試已發現並修復音檔、狀態語意、操作入口、併發、刪除撤權與部署設定等問題。
- 修復後的合成 E2E 與正式環境技術驗收已通過，但李永仁第二輪真實高量測試尚未完成，因此 Input 尚未取得真人閉環驗收。
- Knowledge Answer Reliability KQ0–KQ7 已有技術 Gate 與 production off-mode 證據；這不自動等於租戶能在真實內容上持續獲得正確、完整、可理解的答案。
- 現有場景 Pack 已證明可從核心安裝、停用及物理排除，但產品需求、工作流程與商業價值尚未逐一經真實使用者證實。
- P5 商用規模容量／soak 為 `WAIVED / NOT RUN`；實體行動裝置、共享式多租戶 production FORCE RLS、外部滲透、法律簽核、客戶端 DR 與正式外部連接器仍有開放 Gate。

因此，本文件狀態是 **可以開始執行稽核，但稽核尚未完成**。在最終報告產生前，不得用本文件宣稱「全產品已通過」或「已達商業 GA」。

---

## 1. 為什麼需要 Product Reality Audit

李永仁第一輪測試揭露的不是單一 WAV bug，而是產品判定方式的系統性落差：

1. 把「程式有此能力」誤認為「使用者能完成工作」。
2. 把「API 或元件測試通過」誤認為「完整跨服務旅程通過」。
3. 把「服務健康」誤認為「所有必要外部 Provider 可用」。
4. 把「開發者看得懂狀態」誤認為「第一次使用的客戶知道下一步」。
5. 把「合成格式通過」誤認為「客戶實際設備產生的媒體格式通過」。
6. 把「單筆成功」誤認為「並行、長時間、離開頁面、重試與刪除都成功」。
7. 把「某一層 PASS」擴張成「產品整體 Ready」。
8. 測試曾被延後或豁免，但產品宣稱沒有同步降級。

Product Reality Audit 的用途，就是讓未來任何「已完成」「可供客戶使用」「可商用」的結論，都必須對應到明確環境、版本、角色、資料、旅程、結果與可重跑證據。

---

## 2. 稽核與既有計畫的關係

本稽核是跨產品的橫向驗證層，不重做既有工程計畫：

| 既有計畫／證據 | 本稽核如何使用 | 不可被它替代的事項 |
|---|---|---|
| Input I0–I9 | 作為格式、處理、復原與正式 E2E 的技術基礎 | 真實客戶大量來源、實機、弱網與使用者理解 |
| Knowledge KQ0–KQ7 | 作為 Evidence Decision、Answer Plan、衝突與部分回答的技術基礎 | 租戶真實問題的答案正確性、可用性與工作成果 |
| Application A0–A8 | 作為 Pack 可安裝、停用、移除及核心不反向依賴的證據 | 每一場景是否值得存在、流程是否符合現場工作 |
| Productization P0–P8 | 作為發布、安全、隔離、復原、容量、UX 與營運計畫 | P5 被豁免、P7／P8 未完成及所有外部人工 Gate |
| `OPEN_GATES.md` | 作為既有未關閉事項來源之一 | 本稽核發現的新缺口與文件間矛盾 |
| README／使用手冊／銷售說法 | 作為能力宣稱待核對清單 | 程式、正式部署旗標與真人驗收的真實狀態 |

本稽核不得把既有 Code Review 文件的 `PASS` 直接轉記成「產品 PASS」。每一項仍需確認它證明的是程式、測試環境、正式環境，還是真人工作成果。

### 2.1 與 Knowledge KQ 計畫的邊界

- KQ 計畫負責「問答決策機制是否正確、可測、可回滾」。
- Product Reality Audit 負責「整個產品從登入、Input、人工確認、發布、問答、引用、撤權到營運，是否真的能被客戶完成」。
- KQ Gate 通過是 Ask 稽核的必要證據之一，不是全產品驗收。

### 2.2 與李永仁第二輪測試的關係

李永仁第二輪測試是第一租戶真實驗收的重要證據，但不是全產品唯一證據。它主要覆蓋八策已啟用的 Input＋Knowledge／Ask 核心；未啟用的場景 Pack、共享式多租戶、正式外部連接器、商用規模容量及法律／資安 Gate 仍需各自驗證。

---

## 3. 「真實可用」的六級狀態

所有能力、頁面、API、Provider 與模組都必須使用下列狀態，不得只寫「完成」。

| 等級 | 狀態 | 判定方式 | 可以宣稱什麼 |
|---:|---|---|---|
| R0 | 已設計 | 有需求、契約、畫面或 ADR | 僅能說已規劃 |
| R1 | 已實作 | 程式存在、靜態檢查與 Code Review 通過 | 僅能說工程實作完成 |
| R2 | 自動測試通過 | 可重跑的 unit／integration／contract／E2E 通過 | 僅能說指定測試範圍通過 |
| R3 | 正式環境驗證 | 精確 release、正式設定、真 Provider 與正式網域通過 | 可以說已在指定正式版本驗證 |
| R4 | 真人工作驗收 | 非開發者用真實資料完成任務，結果與理解均通過 | 可以說已由指定租戶／角色驗收 |
| R5 | 可重複交付 | 新租戶可依 SOP 自助或標準化交付，監控、復原與支援成熟 | 才能說此能力具產品化交付能力 |

補充規則：

- 任一能力的整體狀態取證據鏈中的最低有效等級，不取最高局部等級。
- `SKIP`、`WAIVED`、`NOT RUN`、`BLOCKED` 不能換算為 PASS。
- R3 只對「該 release＋該環境＋該設定」有效；部署新版後需重新確認關鍵旅程。
- 歷史 release 的 R3 證據不得自動繼承到目前 release；未完成差異分析與必要重驗前，只能標示「歷史 R3／目前 UNVERIFIED」。
- R4 必須記錄角色、裝置、資料類型、任務、成功條件與觀察結果。
- R5 不代表零缺陷，而是失敗可被發現、理解、復原、支援且不破壞安全與資料一致性。

---

## 4. 稽核核心原則

### 4.1 從使用者工作出發

每個測試必須用「使用者要完成什麼」描述，不以「呼叫哪支 API」作為主要成功條件。

錯誤示例：`POST /knowledge/assets` 回傳 202。

正確示例：管理部 Owner 從 iPhone 上傳 DJI 錄音，離開頁面後再回來，能理解處理狀態、完成必要人工確認、發布並從 Ask 取得附時間碼的答案。

### 4.2 前後端與背景工作是同一條旅程

測試不得停在 HTTP 成功。必須追到 terminal state、衍生資料、人工責任、檢索可見性、引用、刪除／撤權與稽核記錄。

### 4.3 成功路徑與失敗路徑同等重要

每個重要能力至少要測：成功、資料不足、權限不足、外部依賴失敗、逾時、重試、重複提交、離線／弱網、重新整理、使用者離開頁面與刪除後一致性。

### 4.4 使用者語意必須對應實際責任

狀態文字必須回答：

- 現在發生什麼？
- 系統還在跑，還是等待人？
- 誰要做下一步？
- 何時應重試或聯絡管理員？
- 失敗時原始資料是否仍安全？

### 4.5 權限與租戶隔離採負面證明

不能只證明 owner 看得到；還要證明不該看到的人、另一租戶、撤權後的使用者、停用 Pack 與被刪除來源確實看不到、搜不到、問不到、下載不到。

### 4.6 宣稱必須可追溯

每項產品宣稱都要連到：

```text
Claim
  → Capability / Journey
  → Release + Environment
  → Test Case + Dataset
  → Artifact + Timestamp
  → Reviewer / Tenant acceptance
  → Expiry / Revalidation trigger
```

### 4.7 稽核與修復分開記錄

發現問題後可以修復，但不得直接覆蓋原結果。必須保留：第一次失敗、根因、影響範圍、修復 commit、Code Review、回歸測試、正式部署與真人複測。

---

## 5. 證據可信度排序

由強到弱如下：

1. 真實租戶、真實使用者、真實資料與真實裝置完成工作並簽認。
2. 正式網域、精確 release、真 Provider 的端到端旅程證據。
3. Production-like staging 的跨服務、跨角色與故障注入證據。
4. 自動化 browser／API／integration／contract 測試。
5. 單元測試、靜態掃描與架構掃描。
6. 程式碼存在、畫面原型、文件描述或人工推論。

低層證據不能取代高層證據。高層證據若只覆蓋一種資料或一個角色，也不能外推成所有格式、角色與租戶皆通過。

---

## 6. 全產品稽核範圍

### 6.1 Release、環境與版本真實性

確認項目：

- `/health`、`/release.json`、container image、source commit、migration head、route hash 與 deployment manifest 完全一致。
- 正式流量只進入核准 release；舊容器、舊環境檔與測試 Compose 不得誤接流量。
- canonical secrets／env 不被 release 目錄舊副本覆蓋。
- migration、frontend bundle 與 backend API 不會出現半套部署。
- rollback 能回到可用版本，且資料 schema／索引／物件仍相容。
- README、操作手冊、正式 UI 的版本宣稱與 runtime 一致。

主要風險：先前已發生 release 目錄舊 env 使 Provider 回退錯誤設定，因此此區列為每次發布的阻擋 Gate。

### 6.2 登入、帳號與工作空間載入

覆蓋：

- 首位 Owner 建立、邀請第二位使用者、停用、重啟用與密碼重設。
- 一般登入、token 過期、重新整理、登出、不同裝置登入與 session 失效。
- email verification、MFA enrollment／recovery、SSO mock／正式設定（依租戶啟用狀況）。
- 工作空間載入失敗、重試與重新登入文案是否可理解。
- 登入後公司名稱、部門、權限、已啟用核心與 Pack 是否正確。
- 未授權 deep link 不得先閃現資料再轉址。

成功結果：第一次使用者不用知道內部角色模型，也能進入正確工作空間並理解能做什麼。

### 6.3 多租戶、角色、權限與資料生命週期

覆蓋：

- Owner、管理者、建立者、審核者、一般使用者與停用帳號。
- 同租戶跨部門、資源 ACL、deny、分享、下載與引用。
- 兩個租戶相同檔名、相同內容 hash、相同問題與相同 Pack 的隔離。
- application role、maintenance role、schema owner 與 worker 權限邊界。
- 建立、撤權、封存、tombstone、hard delete、retention、legal hold 與 export。
- cache、搜尋索引、向量索引、相容 Document projection、引用與已產生報告同步撤權。
- 專屬單租戶部署與共享式多租戶部署不得混用同一 Ready 宣稱。

特別 Gate：正式 shared multi-tenant 在 FORCE RLS、canary、攻擊矩陣與觀察期完成前，不得標示 R5。

### 6.4 多元 Input 與來源建立

來源範圍：

- 文件：PDF、DOCX、XLSX／CSV、PPTX、TXT、可搜尋 PDF、掃描 PDF、混合頁面。
- 圖片：JPG、PNG、HEIC（若宣稱支援）、直拍、橫拍、旋轉、陰影、模糊、手寫與表格。
- 音檔：WAV PCM16／PCM24、M4A／AAC、MP3、長音檔、多人、靜音、噪音、損壞與副檔名不符。
- 影片：MP4／MOV、手機／相機實拍、含／不含音訊、長影片、旋轉 metadata、不同 codec、異常中斷。
- 現場擷取：拍照、錄音、錄影、長時間錄音、鎖屏／切換 App／來電中斷、權限拒絕。
- 其他入口：網址、NAS／SMB、批次匯入、分段上傳、外部紀錄與已啟用連接器。

每種來源都要驗證：

1. 上傳前格式、大小、資料分類與同意提示。
2. 上傳進度、續傳、取消、重複檔案與併發 admission。
3. malware scan、hash、ACL、asset/revision identity。
4. 背景處理、heartbeat、lease、retry、dead-letter 與 stale reconciliation。
5. OCR／ASR／影像衍生物與信心值。
6. terminal state 與使用者下一步。
7. 原始檔仍可追溯，衍生內容不冒充正式知識。
8. 刪除／撤權後搜尋、Ask、引用與下載立即或在明示 SLA 內失效。

成功結果不是「上傳成功」，而是來源能安全到達「等待人工確認」或「已可問答」，失敗時也能知道原因與復原方式。

### 6.5 人工確認、證據治理與發布

覆蓋：

- 來源分組而非候選筆數造成的認知負擔。
- AI 建議、正式原文、人工修改與最終發布值的視覺區隔。
- 低信心、衝突、高風險、過期、缺適用範圍與缺來源的處理。
- 建立者不可自核的規則是否只在需要時出現，且文案說明由誰處理。
- 核准、退回、補件、批次處理、部分核准與重複操作冪等。
- 發布後 KnowledgeUnit／Release／membership／quality state 是否一致。
- 正式 SOP 衝突、版本優先序、生效日及適用機台／角色。
- 審核紀錄、稽核事件與通知是否完整且不洩漏敏感內容。

成功結果：審核者能判斷「我為什麼要看、要決定什麼、根據什麼、決定後會發生什麼」。

### 6.6 企業知識、版本與權威

覆蓋：

- SourceAsset、AssetRevision、DerivedArtifact、EvidenceSpan、KnowledgeUnit、KnowledgeUnitRelease 的鏈結。
- draft、ready、active、superseded、revoked、expired、tombstoned 的讀取規則。
- 文件改版、舊版保留、生效日、適用範圍與回滾。
- 同一事實多來源、來源衝突、權威來源優先與人工裁決。
- 表格同列、公式、日期、集合、程序步驟與跨來源 relation。
- 搜尋、Wiki、Ask、報告及 Pack 對相同知識狀態的讀取一致性。
- 已刪除或未發布內容不得因 cache／legacy projection／sidecar 殘留再次出現。

### 6.7 Ask、檢索、答案與引用

題型至少包含：

- 單一明確事實。
- 多份文件彙整。
- 表格欄位與同列約束。
- 日期／版本／適用範圍。
- 程序步驟、前置條件、風險與例外。
- 音訊說話者與時間碼。
- 影片畫面、OCR、動作候選與時間軸。
- 不完整證據、來源衝突、無答案與權限禁止。
- 追問、改題、長對話、同步與串流一致性。
- 中英文、口語、錯字、縮寫與製造業用語。

必驗產品狀態：

| 狀態 | UI 必須表達 | 系統不得做的事 |
|---|---|---|
| 完整回答 | 結論、來源、版本、定位 | 引用不支援答案的來源 |
| 部分回答 | 已知、未知、缺少條件 | 把部分證據寫成完整結論 |
| 來源衝突 | 衝突內容、各自來源、下一步 | 靜默選一份當真相 |
| 無可用證據 | 找不到的範圍與可採取行動 | 自由生成確定事實 |
| 權限禁止 | 不揭露存在性或敏感 metadata | 以錯誤訊息洩漏他租戶內容 |
| 系統執行失敗 | 可重試、追蹤碼、資料安全狀態 | 偽裝成「知識庫沒有答案」 |

引用必須能打開正確來源、精確 revision、頁碼／儲存格／段落／時間碼，且使用者仍具權限。Ask 通過不只看語句流暢，還要驗證 claim 是否被 citation 支援。

### 6.8 搜尋、Wiki、圖譜與其他知識表面

覆蓋：

- 搜尋結果與 Ask 使用相同 ACL、release 與撤權語意。
- 文件層、chunk 層、typed unit 與 relation 不互相製造矛盾。
- Wiki 編譯、重編、版本、來源與撤權同步。
- Graph／關聯查詢不得跨 tenant 或跨不可見 revision。
- legacy sidecar 回傳內容仍需經核心 PEP／CitationBuilder。
- 空結果、部分 provider 降級與索引延遲要有可理解狀態。

### 6.9 外部來源與連接器

每個宣稱支援的連接器分別驗證：

- 建立、驗證、停用、刪除與 secret rotation。
- 初次全量同步、增量同步、重複事件、pagination 與 rate limit。
- 上游 ACL、資料夾移動、檔案改名、更新、刪除與權限撤銷。
- token 過期／refresh、401／403／429／5xx、網路中斷與 webhook replay。
- 同步狀態、錯誤說明、重試與管理員通知。
- 連接器停用後既有知識的保留／撤銷政策。

未持有正式憑證的 SharePoint／Google Drive 等，只能標記 R2 mock/contract，不得宣稱 R3 或 R4。

### 6.10 Governance、稽核與管理

覆蓋：

- 公司、部門、使用者、Owner、模組與資料分類設定。
- Audit log 的 actor、tenant、resource、action、result、timestamp 與追蹤碼。
- 一般管理者不能查看平台級秘密或他租戶 metadata。
- 用量、配額、超額、成本與 Provider 狀態是否和真實執行一致。
- 備份、部署、健康、Input pilot、decision diff 等系統頁面只對適當角色開放。
- 管理頁面應以營運工作描述，不要求租戶理解內部資料模型。

### 6.11 外部 AI／媒體／儲存 Provider

必要能力逐項 live probe，不以「API key 存在」當成功：

- 主問答模型。
- 內部分類／整理模型。
- embedding／rerank。
- OCR／掃描理解。
- 短語音 STT／TTS。
- 長音檔 ASR／diarization。
- 影片 ffmpeg／ffprobe 與選用視覺模型。
- malware scanner。
- object storage／S3 相容儲存。
- email、SSO、通知及付款（若產品宣稱或租戶啟用）。

每條 Provider 都要測正常、無 key、錯 key、權限不足、quota、429、timeout、5xx、response schema 改變與 fallback。Fallback 必須維持資料分類、租戶、品質與成本政策，不得靜默降低可信度。

### 6.12 工作流與內容產出

共用 Workflow Kernel 覆蓋：

- 任務建立、指派、狀態、期限、補件、退回、核准與稽核。
- 表單模板、instance、欄位 validation、草稿、版本與匯出。
- 待辦中心依責任人、風險與期限顯示。
- 通知重送與冪等，不得產生重複任務或重複核准。
- Generate／Reports／匯出內容要保留來源、權限與版本，不可把 AI 草稿標成正式事實。

### 6.13 場景 Pack 與模組生命週期

目前需盤點的可部署 Application Pack 至少包括：

- `sales_quote`
- `incident_handover`
- `quality_8d`
- `training_knowhow`
- `mka` legacy/composition shell

另有 Knowledge Decision／Knowledge Provider contribution，需在 PRA3 與 PRA5 盤點，但不能誤列為完整場景 Application Pack：

- `manufacturing_knowledge`
- `hr_knowledge`／`hr_compatibility`

PRA0 必須以 runtime `PackRegistry`、frontend build-time bundles、tenant binding 與 deployment flags 重建最終清冊，不以目錄存在就判定為已安裝產品。

每個 Pack 都要分成兩種稽核：

#### A. 技術模組性

- 未部署時不 import implementation。
- 未綁定租戶時 UI、API、route、job、retrieval contribution 均不可用。
- 安裝、升級、停用、重啟用、rollback 與物理排除可重複。
- 停用後核心 Input、Knowledge、Ask、Workflow 仍可運作。
- orphan data、migration、背景任務與 navigation 不殘留。
- Pack 不得繞過核心 ACL、release、Evidence Decision、Citation 或 audit。

#### B. 產品真實性

每個 Pack 必須回答並經真人驗證：

1. 誰在什麼時候進入？
2. 要完成什麼具體工作？
3. 系統可從文件、語音、照片、影片、掃碼或既有資料帶入什麼？
4. 缺資料時如何引導補齊？
5. 哪些是 AI 建議、正式來源與人工必填／必確認？
6. 完成後產生什麼可用成果？
7. 是否需要送審、退回、追蹤、交接或通知？
8. 如何回到正式 SOP、規格與原始證據？
9. 手機、平板與桌機是否符合現場？
10. 成效如何量測？

技術模組性通過不代表 Pack 具有市場價值。未通過真人需求與任務驗證的 Pack 應標為「產品假設」，不可出現在核心產品 Ready 宣稱中。

### 6.14 行動裝置、瀏覽器與無障礙

最低矩陣：

| 類型 | 必測環境 | 代表工作 |
|---|---|---|
| 桌機 | Chrome、Edge，1280×720 與常用企業解析度 | 管理、審核、品質、Ask、模組設定 |
| iPhone | 實體 iPhone Safari | 登入、拍照、錄音、錄影、上傳、狀態追蹤、Ask |
| Android | 實體 Android Chrome | 同上，另含檔案選擇器與返回鍵 |
| 平板 | 至少一個實體或受控裝置 | 現場查看、審核、影片證據 |
| 弱網 | 高延遲、低頻寬、斷線重連 | 續傳、背景處理、重試、草稿保存 |
| 無障礙 | keyboard、focus、screen reader 基礎、contrast、zoom 200% | 所有主要旅程 |

瀏覽器 responsive 模擬只能算 R2/R3 的部分證據，不能取代實體 media permission、鎖屏、相機、麥克風與檔案選擇器驗收。

### 6.15 效能、容量、成本與長時間穩定性

覆蓋：

- Lite／Standard／Enterprise 或實際銷售 profile 的 CPU、RAM、disk、queue、DB pool 與 object storage。
- 單筆大檔、多筆小檔、四格式併發、多租戶公平排程與長媒體。
- Ask P50／P95／P99、Input terminal time、review backlog、index lag 與撤權收斂時間。
- 72 小時 soak 或核准的等效長期證據。
- Provider token、OCR、ASR、儲存、egress 與人工審核成本。
- quota／rate limit 生效時的 UX，不得只看到 429。
- 滿載時降級、拒絕、恢復與資料一致性。

P5 現有 `WAIVED / NOT RUN` 必須在產品狀態中保持為 HOLD，直到真實 profile 證據完成。

### 6.16 韌性、備份、還原與營運支援

覆蓋：

- web／worker／Redis／PostgreSQL／object storage／Provider 個別故障。
- WorkerLost、OOM、disk full、queue backlog、DB deadlock、migration failure 與 partial deploy。
- retry、dead-letter、stale reconciliation 與告警 fire/recover。
- tenant-scoped backup、全系統 backup、restore、index rebuild、設定與 secrets recovery。
- RTO／RPO 在實際部署 profile 上驗證。
- support bundle 不含 API key、token、prompt、跨租戶 metadata 或未遮罩個資。
- runbook 由非原開發者照著完成，而不是作者本人憑記憶操作。

### 6.17 安全、隱私、合規與商業交付

覆蓋：

- SAST、dependency、container、secret scan、DAST 與第三方滲透。
- 檔案惡意內容、MIME 偽裝、zip bomb、超大檔、prompt injection 與來源污染。
- 錄音錄影同意、個資、人臉、客戶資料、營業秘密、跨境與 retention。
- 模型及第三方元件商用授權、DPA、資料處理地點與刪除承諾。
- onboarding、SLA、support、incident communication、offboarding 與資料匯出。
- 帳單／付款只在正式納入產品時執行 sandbox 與真商戶驗收。

外部滲透、法律意見與客戶簽核不可由內部自動測試取代。

### 6.18 公開網站、登入前體驗與客戶溝通

覆蓋：

- Landing page、登入頁、錯誤頁、服務中斷頁、Terms、Privacy、Cookie／追蹤同意（如有）。
- 網站宣稱、價格／方案、支援格式、安全與部署模式是否和 runtime capability 一致。
- 未登入使用者不可透過 metadata、preview、搜尋引擎索引、source map 或錯誤頁取得租戶資訊。
- 邀請信、驗證信、重設密碼、系統通知與支援訊息的寄件者、連結、期限與行動裝置體驗。
- incident／maintenance／degradation 對客戶的狀態與通知，不得只在內部監控可見。

### 6.19 API、Webhook 與相容性

覆蓋：

- OpenAPI 與實際 route、request、response、status code、pagination、rate limit 及錯誤契約一致。
- tenant、subject、scope、idempotency key、resource ID 與 tracing header 不可被客戶端偽造繞過。
- 同步／串流、browser／API client 與 legacy redirect／deprecation 行為一致。
- webhook 驗簽、重送、亂序、重複、逾時與死信；重試不得重複副作用。
- breaking change、migration window、棄用 telemetry、通知、停用與 rollback。
- API Guide／Developer Guide 的範例只能使用仍存在且被支援的契約。

### 6.20 部署模式、安裝、升級與移轉

覆蓋：

- managed private cloud、單機／地端、專屬租戶與 shared multi-tenant 的能力差異及安全前提。
- fresh install、既有資料 upgrade、跨版本 migration、N-1 rollback 與重大版本移轉。
- secrets、憑證、object storage、ffmpeg、scanner、worker、DB role 與 Provider prerequisite 檢查。
- 備份來源版本與還原目標版本的相容性。
- 安裝／升級 runbook 由非作者執行，失敗時不得留下半套 schema、bundle 或 routing。
- `mobile/`、legacy UI、sidecar 或其他隨產品交付的 surface 必須被正式納入、標為相容層，或走退場程序；不得處於無 owner 狀態。

---

## 7. 端到端關鍵旅程

### J01：新租戶標準化開通

```text
建立租戶
  → 建立首位 Owner
  → 設定公司／部門
  → 選擇核心能力與 Pack
  → 寄送／完成登入
  → 顯示正確工作空間
  → 產生可稽核交付紀錄
```

通過條件：不需工程師手改 DB；錯誤可回滾；不建立示範資料殘留；租戶只看見被授權功能。

### J02：混合來源 Input 到可問答

```text
文件＋圖片＋音檔＋影片
  → 上傳／續傳／離開頁面
  → 背景處理
  → 等待人工確認
  → Owner／審核者處理
  → 發布
  → 已可問答
```

通過條件：狀態、責任與下一步清楚；所有來源可追溯；失敗來源可診斷與安全重試；數量顯示以使用者工作單位表達。

### J03：Ask 到證據

```text
提出真實工作問題
  → 檢索可見且有效版本
  → Evidence Decision
  → 完整／部分／衝突／無證據／執行失敗
  → Answer Plan
  → 答案＋引用
  → 打開原始頁面／表格／時間碼
```

通過條件：答案狀態真實、引用支援 claim、無權限資料不洩漏、使用者知道下一步。

### J04：更新、撤權與刪除

```text
來源改版或撤權
  → 新 revision／權限事件
  → projection／index／cache 收斂
  → Ask／搜尋／Wiki／報告一致
  → 稽核與復原政策生效
```

通過條件：舊資料不因任何讀取表面殘留；保留政策和 hard delete 邊界清楚。

### J05：失敗與恢復

```text
Provider timeout／worker crash／網路中斷
  → 使用者看到正確狀態
  → 系統安全重試或要求人工動作
  → 不重複 side effect
  → 告警與追蹤碼
  → 恢復後完成或明確終止
```

通過條件：不能永久卡住、不能把系統失敗說成沒有知識、不能遺失原始來源。

### J06：Pack 安裝到移除

```text
部署可用
  → 租戶安裝／設定
  → 使用者執行工作
  → 升級／停用
  → 重啟用或移除
  → 核心仍正常
```

通過條件：UI、API、job、retrieval、資料與權限同步；不需 fork core；移除後沒有孤兒入口或背景工作。

### J07：租戶離場

```text
提出 export／刪除
  → 身分與範圍確認
  → 匯出來源、版本、知識、稽核與設定
  → retention／legal hold 判斷
  → 刪除與索引撤銷
  → 可驗證完成證明
```

通過條件：資料完整、格式可用、刪除不誤傷他租戶且無隱藏殘留。

### J08：發布、升級與回滾

```text
核准 release
  → 備份／preflight
  → migration＋backend＋worker＋frontend
  → parity／provider／核心旅程 smoke
  → 觀察與告警
  → 成功確認或 N-1 rollback
  → 客戶可理解的狀態與紀錄
```

通過條件：不出現新舊 bundle、schema、route 或 env 混用；rollback 後資料與核心旅程仍一致；歷史版本證據不被誤當成目前 release 的驗證結果。

---

## 8. Persona 與權限測試矩陣

避免重新建立複雜且僵硬的多角色產品介面。本稽核以「能力／責任」驗證權限，租戶可將能力授予少量實際使用者。

| 測試身分 | 主要責任 | 必驗事項 |
|---|---|---|
| Tenant Owner | 公司、成員、模組、治理與高風險核准 | 所有管理能力、不可跨租戶、建立者自核限制 |
| Knowledge Steward／授權審核者 | 來源確認、衝突、發布、版本 | 能看到所需證據，不能取得未授權公司設定 |
| Contributor／建立者 | 上傳、錄音錄影、補資料 | 能追蹤自己的來源，不能繞過發布／高風險核准 |
| Knowledge User | 搜尋、Ask、查看引用 | 只讀已發布且獲授權內容 |
| Platform Operator | 部署、健康、備份、支援 | 經稽核的跨租戶維運，不可作一般內容瀏覽 |
| Disabled／Revoked User | 無有效存取 | 所有 token、deep link、下載與 Ask 均拒絕 |
| Tenant B Adversary | 模擬跨租戶探測 | 不得從 ID、檔名、錯誤、搜尋、引用或時間差得知 Tenant A 資料 |

八策目前兩位使用者皆為 Owner，這適合早期試用，但不能代替一般使用者與受限權限負例。稽核資料可建立專用合成測試身分，不要求租戶真的增加複雜角色。

---

## 9. 測試資料矩陣

### 9.1 資料分層

| Corpus | 用途 | 是否可公開結果 | 是否可重跑 |
|---|---|---|---|
| 合成固定 corpus | 防回歸、錯誤注入、跨租戶與刪除 | 可 | 必須 |
| 去識別內部 corpus | 文件版面、媒體、製造用語 | 依政策 | 必須 |
| 公開授權 corpus | 外部可重現品質 | 可 | 必須 |
| 租戶真實 corpus | 真人工作驗收與未知格式 | 不可外流 | 經租戶核准後重跑 |
| sealed holdout | 防止對測試題特化 | 僅摘要 | 首跑保存 |

### 9.2 必含邊界樣本

- 空白、極短、極長、重複、損壞、加密、受密碼保護與 MIME 偽裝。
- 掃描、旋轉、低解析、陰影、手寫、混合語言、複雜表格與合併儲存格。
- 單人／多人、噪音、重疊語音、靜音、PCM24、行動裝置錄音與 DJI 等真實設備格式。
- 有聲／無聲影片、長影片、codec 不支援、畫面與語音不同步。
- 相同檔名不同內容、相同內容不同 ACL、跨租戶相同 hash。
- 新舊版互相衝突、正式 SOP 與口述經驗衝突、已過期與未來生效文件。

### 9.3 防特化規則

- 測試題與檔名不得寫入 production code 特判。
- 首次 holdout 結果與 threshold manifest 要在調整前保存。
- 修復已知案例後，加入 neighbor cases，而不是只讓原題通過。
- 測試資料、預期答案、評分器與 production prompt／retrieval 設定要版本化。

---

## 10. 缺陷分級與處置

| 等級 | 定義 | 範例 | 發布處置 |
|---|---|---|---|
| P0 Critical | 跨租戶、資料遺失、未授權洩漏、惡意執行、不可回復錯誤 | Tenant B 讀到 Tenant A、刪除錯租戶 | 立即停止／回滾，禁止測試擴量 |
| P1 High | 核心旅程無法完成、錯誤答案被當確定事實、撤權失效、普遍性故障 | 音檔普遍失敗、AI 引用已刪除來源 | 阻擋租戶驗收與發布 |
| P2 Medium | 可繞過但造成明顯困惑、重工或營運風險 | 不知道誰要審核、錯誤文案無下一步 | 修復後再做該旅程真人複測 |
| P3 Low | 不阻擋工作的一致性、視覺或便利性問題 | 次要間距、非關鍵排序 | 可帶 owner、期限進受控 Pilot |

所有缺陷紀錄至少包含：

- ID、日期、發現者、租戶／測試 corpus。
- release、環境、裝置、瀏覽器、網路。
- 前置條件、重現步驟、預期、實際。
- 追蹤碼、source／asset／job ID（需遮罩）。
- 影響範圍與是否涉及其他租戶／資料生命週期。
- 根因，不只寫表面症狀。
- 修復 commit、migration、旗標、部署 release。
- 自動回歸、正式複測與真人複測結果。
- 是否要擴大檢查相鄰流程。

### 10.1 擴大診斷規則

每個問題都要追問：

1. 同一狀態是否出現在其他頁面、API 或背景工作？
2. 同一格式／Provider 的其他入口是否也會失敗？
3. 同一 tenant／ACL 契約是否被其他模組繞過？
4. 同一錯誤在併發、重試、刪除、改版與回滾時如何表現？
5. 監控能否在使用者回報前發現？
6. 文件、測試、UI 文案與能力宣稱是否都要更新？

---

## 11. 稽核執行階段

每一 Phase 均遵守：**稽核 → 缺陷／差距登錄 → 必要修復 → 測試 → Code Review → 重跑 Gate → 才能進下一 Phase**。若 Phase 只產生證據沒有修改程式，仍需做 Evidence Review，確認沒有以弱證據作過度宣稱。

執行分成兩條證據軌，但仍維持 Phase Review 順序：

- **Internal／Engineering 軌：** repository、isolated、staging、production technical evidence。能由內部完成者不得等待客戶才做。
- **Human／External 軌：** 真實租戶、實體設備、外部憑證、第三方滲透、法律與客戶 DR。外部證據未到時標為 OPEN／HOLD，不得偽裝 PASS；但只要當期內部 Gate 已完成 Review，可繼續後續內部稽核。

換言之，外部等待不應讓內部改善停工，但 PRA9 最終 R4／R5／GA 決策仍會被必要的 OPEN／HOLD Gate 阻擋。

### PRA0 — 基線凍結與產品表面清冊

目標：知道正式環境到底部署什麼、宣稱什麼、使用者看得到什麼。

工作：

- 凍結 production release identity、env capability digest、migration、route、Pack 與 Provider 狀態。
- 列出全部 frontend routes、API routers、背景 jobs、資料表、連接器、Provider、feature flags 與 legacy redirects。
- 建立 Claim Registry，對照 README、使用手冊、API 文件、公開網站、正式 UI 與銷售文件。
- 將每項能力先標 R0–R5、PASS／HOLD／FAIL／NOT RUN，未知一律標 `UNVERIFIED`。
- 建立缺陷 register 與 evidence manifest schema。

Gate `PRA-BL-01`：清冊可由程式重建；正式 release 可識別；不存在未標示 owner 的產品表面；所有「完成」宣稱已轉成六級狀態。

### PRA1 — 登入、租戶、權限與工作空間

目標：任何後續測試都建立在可信身分與租戶邊界上。

工作：

- 執行 J01、帳號生命週期、capability、deep link 與跨租戶負例。
- 驗證專屬租戶現況，另以 production-like staging 驗證 shared multi-tenant／FORCE RLS。
- 驗證 Owner 雙人設定及最小權限合成身分。
- 驗證 token、MFA／SSO（依啟用狀況）、停用帳號與 workspace bootstrap 失敗。

Gate `PRA-ID-01`：P0/P1 身分或隔離缺陷為 0；所有角色看到的導航、API 與資料一致；共享式與專屬式 Ready 宣稱分離。

### PRA2 — Input、處理、人工確認與發布

目標：從多元來源到正式知識的完整核心旅程可重複。

工作：

- 執行 J02，覆蓋文件、圖片、音訊、影片、現場擷取與批次。
- 驗證真實裝置格式、長檔、併發、續傳、離頁、重試、WorkerLost 與 Provider failure。
- 驗證狀態責任、審核分組、補件、高風險核准與發布。
- 執行李永仁第二輪真實高量測試；保留原始失敗與複測證據。

Gate `PRA-IN-01`：核心格式 terminal-state rate 達預先凍結門檻；P0/P1 為 0；內部技術證據完成 Review。八策真人 Input 驗收必須另標 `R4 PASS` 或明確 `OPEN/HOLD`；未取得 R4 不阻止後續內部稽核，但阻止 Core 的真人驗收宣稱。

### PRA3 — Knowledge、Ask、引用、改版與撤權

目標：使用者拿到的是可證明、可理解且權限正確的答案。

工作：

- 執行 J03、J04，覆蓋完整、部分、衝突、無證據、禁止與 execution failure。
- 比對 sync／stream、搜尋／Wiki／Ask、舊新 revision 與各種 evidence locator。
- 對租戶真實問題做人工 ground truth；檢查 Answer Plan 與 citation support。
- 執行刪除、撤權、Pack 停用、來源過期與 cache/index invalidation。

Gate `PRA-KB-01`：critical false acceptance、跨租戶 citation、已撤權引用與 execution failure 偽裝為無答案均為 0；租戶可從答案回到精確證據。

### PRA4 — UX、裝置、可理解性與無障礙

目標：不熟悉系統的人可在實際工作環境完成核心任務。

工作：

- 由未參與開發的人執行登入、Input、審核、Ask、引用及錯誤復原。
- 實體 iPhone／Android／平板及桌面瀏覽器矩陣。
- 弱網、鎖屏、返回鍵、權限拒絕、離線、zoom、keyboard 與 focus。
- 記錄任務完成率、時間、求助次數、誤解、錯誤恢復與信任問題。

Gate `PRA-UX-01`：核心任務達預先凍結的完成率；沒有 P0/P1；狀態責任理解率達門檻；實體裝置 Gate 不再以 responsive 模擬替代。

### PRA5 — Provider、連接器與外部整合

目標：所有啟用或宣稱能力在真實憑證、錯誤與復原下可用。

工作：

- 建立 Provider capability matrix 與逐條 live probe。
- 執行 NAS／SMB 與所有啟用連接器的 sync／ACL／撤銷／重試。
- 對未提供正式憑證的連接器明確降級為 mock/contract 狀態。
- email、SSO、通知、付款只依實際產品範圍驗證並標示 Ready 層級。

Gate `PRA-EXT-01`：正式啟用 Provider 皆有 live evidence；錯誤不靜默 fallback；連接器權限與刪除一致；宣稱不超過可用憑證範圍。

### PRA6 — Workflow、輸出與治理

目標：共用工作能力可被模組安全重用，管理員能營運而非只看技術資料。

工作：

- 測任務、表單、審核、待辦、通知、Generate、Reports 與 export。
- 測公司、部門、使用者、audit、usage、quota、health 與 support flow。
- 驗證 AI 草稿、人工確認與正式輸出的區隔。
- 驗證重送、重複點擊、併發核准與冪等。

Gate `PRA-WF-01`：工作狀態、責任、證據與稽核一致；輸出不越權；重試不造成重複 side effect。

### PRA7 — 每一個場景 Pack 零基真人稽核

目標：逐一決定 Pack 是可交付產品、需重設的假設、技術模板或應封存功能。

工作：

- 對每個 Pack 執行技術模組性測試 J06。
- 逐一完成十個產品真實性問題、persona journey、資料帶入、成果與成效指標。
- 至少一位目標工作者完成任務測試；未取得真實證據不得升級為 R4。
- 產出 `KEEP / REDESIGN / PILOT ONLY / TEMPLATE / RETIRE` 決策。

Gate `PRA-PACK-01`：每個 Pack 有獨立結論；核心 Ready 狀態不被未驗證 Pack 拉高或拖累；任何 Pack 都能停用且核心正常。

### PRA8 — 容量、韌性、安全與交付營運

目標：證明系統在真實負載與故障下可維持資料正確並可支援。

工作：

- 完成實際銷售 profile 的 load、burst、long media、fairness、soak 與成本。
- 重跑備份、還原、rollback、Provider／worker／DB／storage 故障注入。
- 完成內部安全矩陣，並列出外部滲透與法律 Gate。
- 執行 J07、support bundle、runbook 非作者操作與 incident drill。
- 執行 J08，驗證最新候選 release 的升級、parity、核心 smoke 與 rollback。

Gate `PRA-OPS-01`：P5 不再是 WAIVED；RTO/RPO、容量、成本與降級有真實證據；P0/P1 安全／資料缺陷為 0；外部 Gate 有 owner 與狀態。

### PRA9 — 全產品認證與宣稱收斂

目標：形成單一、可重跑、不可假綠的產品決策。

工作：

- 聚合 PRA0–PRA8 artifact，不以 checkbox 代替原始證據。
- 對 capability claims、README、正式 UI、使用手冊與 deployment flags 做一致性掃描。
- 產出 Core、各 Pack、各部署模式的獨立 Ready 等級。
- 產出 `PASS / CONTROLLED PILOT / HOLD / FAIL`，並列出例外、owner、期限、降級與 rollback。

Gate `PRA-RELEASE-01`：Critical／High correctness、security、tenant isolation、data loss 為 0；必要 Phase 全部有新鮮證據；任何豁免都沒有被記成 PASS；Owner 簽署最終宣稱範圍。

---

## 12. 每階段 Code Review／Evidence Review 標準

每個 Phase 完成後必須建立獨立 Review 文件，至少回答：

1. 本次驗證的是哪個 release、環境、tenant、角色、裝置與 corpus？
2. 哪些是 mock、synthetic、staging、production 或真人證據？
3. 是否有 SKIP、WAIVED、NOT RUN、flaky、重跑才綠或手動介入？
4. 失敗是否保留，還是被最後一次 PASS 覆蓋？
5. 修復是否只針對案例，還是處理了同類根因？
6. 是否新增跨租戶、撤權、併發、重試與 rollback 回歸？
7. UI、API、背景工作、資料與稽核狀態是否一致？
8. 是否把工程 PASS 錯寫成產品／真人 PASS？
9. 是否影響其他核心能力或 Pack 邊界？
10. 下一 Phase 的進入條件是否真的滿足？

Review 只能給出：

- `PASS TO NEXT PHASE`
- `PASS WITH NON-BLOCKING FINDINGS`
- `HOLD — REQUIRED FIXES`
- `FAIL — ROLLBACK / REDESIGN`

禁止使用沒有範圍的「ALL DONE」。

---

## 13. Machine-readable Evidence 設計

建議新增以下 artifact（正式執行時建立，不將原始租戶內容提交 Git）：

```text
artifacts/product_reality/
  PRA_BASELINE_MANIFEST.json
  PRA_CAPABILITY_REGISTRY.json
  PRA_CLAIM_REGISTRY.json
  PRA_JOURNEY_RESULTS.json
  PRA_DEFECT_REGISTER.json
  PRA_PROVIDER_MATRIX.json
  PRA_DEVICE_MATRIX.json
  PRA_PACK_DECISIONS.json
  PRA_RELEASE_DECISION.json
```

每筆 evidence 最低欄位：

```json
{
  "evidence_id": "PRA-...",
  "capability_id": "...",
  "journey_id": "J02",
  "release": {
    "source_commit": "...",
    "image_digest": "...",
    "migration_head": "...",
    "deployment_manifest": "..."
  },
  "environment": "production|staging|isolated|local",
  "deployment_topology": "dedicated|shared|on_prem|local",
  "tenant_class": "synthetic|internal|real",
  "persona": "tenant_owner",
  "device": "...",
  "dataset_id": "...",
  "started_at": "...",
  "finished_at": "...",
  "result": "PASS|HOLD|FAIL|NOT_RUN|WAIVED|SKIP",
  "reality_level": "R0|R1|R2|R3|R4|R5",
  "evidence_scope": "implementation|automated|production|human|repeatable_delivery",
  "is_current_release": true,
  "artifact_refs": [],
  "defect_ids": [],
  "reviewer": "...",
  "expires_at": "...",
  "superseded_by": null
}
```

安全要求：

- artifact 只保存必要 metadata、hash、遮罩識別與結果，不提交原始租戶檔案、答案全文、token、API key 或個資。
- 真實租戶證據存放於 tenant-scoped、加密、有限期的位置；Git 文件只引用受控 evidence ID。
- 不同 release 的結果不可互相覆寫。
- 新 release 不得沿用舊 release 的 `is_current_release=true`；需由差異分析與重驗結果重新核發。
- Gate script 遇到缺欄位、過期、版本不符或 `NOT_RUN/WAIVED` 必須 fail closed。

---

## 14. 指標與預先凍結門檻

門檻應在第一次正式執行前寫入 versioned threshold manifest，不得看完結果再降低標準。

### 14.1 核心成果指標

- 首次登入成功率。
- 核心任務完成率與中位完成時間。
- 無協助完成率、求助次數與錯誤恢復率。
- Input terminal-state rate、處理時間 P50／P95／P99。
- 卡在非 terminal state 的比例與最長時間。
- review 每來源處理時間、退回率、低信心率與衝突率。
- Ask complete／partial／conflict／absent／forbidden／execution failure 分布。
- citation precision、locator 成功率與 claim support rate。
- false acceptance、false rejection 與 critical error。
- 撤權／刪除收斂時間。
- Provider 成功率、timeout、429、fallback 與單位成本。
- 每租戶 queue fairness、容量 headroom、RTO／RPO。
- 每 Pack 任務完成率、成果採用率與節省時間。

### 14.2 不得美化的統計規則

- 重試後成功仍要同時記錄第一次失敗率。
- 排除的樣本要列原因與數量。
- Provider failure 不得混入「知識不足」降低錯答分母。
- synthetic、internal、production、real tenant 指標分開呈現。
- 平均值不得取代 P95/P99 與最差個案。
- 使用者放棄、改用人工或請工程師救援皆視為任務未獨立完成。

---

## 15. 目前已知 Reality Baseline

此表是依 2026-09-03 現有文件形成的稽核起點，不是 PRA 執行後的最終結果。

| 產品區域 | 目前最高可信證據 | 暫定 Reality | 已知缺口 |
|---|---|---:|---|
| Release identity／正式部署 | production health、release metadata、deployment verification | 歷史 R3／目前待 PRA0 確認 | 新 release 仍需逐次重驗；文件狀態可能落後 runtime |
| 八策帳號／雙 Owner | 正式登入與 tenant 歸屬驗證 | R3 | 一般使用者、停用／恢復、真人 onboarding 尚未完整驗收 |
| Input 文件／圖片／PCM24 音訊／短影片 | `dd5a6bd` 正式四格式合成並行 E2E 4/4 | 歷史 release R3 | 最新 production release 必須做差異分析／核心重驗；李永仁第二輪、長媒體、更多設備格式待驗 |
| Input 狀態與手機核心頁 | `dd5a6bd` 正式 390×844 browser 檢查 | 歷史 release R3（部分） | 最新 release、實體 iPhone／Android media stack 與弱網待驗 |
| 人工確認與發布 | `dd5a6bd` 正式合成來源 3 組／16 候選 | 歷史 release R3 | 最新 release 與真人理解、負荷、批次、高風險決策待驗 |
| Ask 與刪除撤權 | `dd5a6bd` 正式唯一碼回答、2 引用；刪除後 0 引用 | 歷史 release R3 | KQ release 後須重驗完整旅程；真實租戶題型、部分／衝突、長對話與持續品質待驗 |
| KQ Answer Decision | KQ0–KQ7 技術 Gate、production off-mode release | R3（部署與技術控制）／R2（實際 tenant enforce 行為） | 受控租戶 live mode、完整旅程與真實使用成果仍需納入 PRA3／PRA4 |
| Pack 技術脫鉤 | A0–A8 code、tests、local browser | R2 | 最新 production 組合與完整 lifecycle 尚需稽核 |
| Pack 產品價值 | 零基盤點文件 | R0–R1 | 各 Pack 真人任務與價值未證明 |
| 專屬第一租戶 | 正式環境已建立 | R3 | 標準化可重複 onboarding/offboarding 待 P7/PRA1 |
| 共享式多租戶 | staging FORCE RLS 證據 | R2 | production application role／FORCE RLS rollout 與觀察期未完成 |
| 外部 Provider 核心 7 路 | production live probes 7/7 | R3 | 持續監控、quota、schema drift 與故障 UX 待稽核 |
| NAS／外部連接器 | 程式與部分 contract／runbook | R1–R2 | 正式憑證、ACL 變動、撤銷與長期同步待驗 |
| 容量／成本／soak | 工程能力完成，live validation waived | R2 | P5 `WAIVED / NOT RUN`，不得宣稱商用容量 |
| 備份／還原／故障注入 | P4 isolated evidence | R2–R3（依環境） | 實際 production profile、非作者演練與客戶 DR 待驗 |
| UI／無障礙 | internal software Gate | R2–R3（部分） | 真機與獨立真人任務測試待驗 |
| 租戶營運／商業沙盒 | P7 列為待完成 | R0–R1 | onboarding、Pack lifecycle、export/delete、通知／SSO／billing |
| 統一產品認證 | P8 列為待完成 | R0 | 尚無單一不可假綠的 product readiness gate |
| 外部資安／法律／現場簽核 | 開放人工 Gate | NOT RUN | 第三方滲透、法律、客戶 DR、現場設備／噪音與 UAT |

### 15.1 立即視為對應 Ready／GA 宣稱 Blocker 的已知事項

下列事項阻擋「商業 GA」或其對應能力宣稱，但不一定阻擋八策受控 Pilot：

- 李永仁第二輪真實 Input→review→publish→Ask→citation 尚未完成。
- P5 live capacity／soak 仍為豁免而非 PASS。
- 實體 iPhone／Android、弱網、長時間真實媒體與工廠噪音未完成。
- shared production FORCE RLS 與 application role rollout 未完成。
- P7 租戶營運／模組生命週期／商業沙盒未完成。
- P8 單一 product readiness gate 未完成。
- 外部滲透、法律／隱私／授權、客戶現場 DR 與 Design Partner UAT 未完成。
- 場景 Pack 的產品價值與真人流程尚未逐一驗證。

### 15.2 複檢時已確認的文件漂移

以下不是推測，而是本文件 v1.1 複檢現有 repository 時已看見的矛盾，應在 PRA0 登錄並收斂：

- `README.md` 的「目前狀態」日期為 2026-09-01，但 repository 已有 2026-09-03 的 Input I9 與 KQ7 production 證據；README 不能作目前 release 的唯一權威。
- KQ Task Plan front matter 已標示 v1.2、`implemented, reviewed and deployed`，但 §0 仍保留「明確開工前不得開始」，§16 仍寫「第一個可執行工作包」。這些歷史啟動文字應標示為已完成或移入歷史紀錄，避免營運誤判。
- `OPEN_GATES.md` 同時寫「剩餘 human gate：1」與列出外部滲透、法律、DR、OAuth、真人 UX、真機、Design Partner 等多種未完成事項；需要按產品範圍與部署模式重建單一 Gate registry。
- Application Pack 的 backend runtime registry、frontend installed bundles、tenant binding 與 Knowledge contribution 並非同一清單；目前不能只用資料夾或文件名稱宣稱某 Pack 已安裝。

---

## 16. 最終產品決策必須分開

PRA9 不產生一個模糊的全產品「PASS」，而是至少分成：

| 決策對象 | 可能結論 |
|---|---|
| Core：專屬單租戶 Input＋Knowledge＋Ask | PASS／CONTROLLED PILOT／HOLD／FAIL |
| Core：共享式多租戶 | PASS／CONTROLLED PILOT／HOLD／FAIL |
| 每個 Input 格式／擷取模式 | 各自 R0–R5 與限制 |
| 每個外部 Provider／Connector | 各自 R0–R5 與啟用條件 |
| 每一個場景 Pack | KEEP／REDESIGN／PILOT ONLY／TEMPLATE／RETIRE |
| 商業 GA | PASS／HOLD／FAIL |

例如，核心專屬 Pilot 可以先通過，不代表 shared SaaS 或所有 Pack 同時通過；某個 Pack 被停用也不應降低核心 Input／Knowledge／Ask 的真實狀態。

---

## 17. 完成定義

Product Reality Audit 只有在以下全部成立時才算完成：

1. PRA0–PRA9 均有版本化 artifact 與 Review 文件。
2. 全部正式產品表面、API、背景工作、Provider、Connector、Pack 與宣稱都有 owner 與 Reality 等級。
3. Core 八條關鍵旅程均在指定 release 可重跑。
4. 真實租戶資料與真人工作驗收不再被合成測試取代。
5. P0/P1 correctness、security、tenant isolation 與 data loss 缺陷為 0。
6. 所有 `SKIP / WAIVED / NOT RUN / UNVERIFIED` 都清楚留在最終決策，沒有被平均成 PASS。
7. README、使用手冊、正式 UI、銷售說法與 deployment flags 一致。
8. 已通過、只限受控 Pilot、尚未驗證與不得宣稱的能力清楚分開。
9. 每個場景 Pack 都有獨立產品與技術結論，可不影響核心地停用或移除。
10. 最終 `PRA_RELEASE_DECISION.json` 與人類可讀報告由 Product Owner 確認。

---

## 18. 建議的第一個工作包

收到明確「開工」指示後，第一階段只執行 PRA0，不直接宣稱或修改產品 Ready 狀態：

1. 建立 machine-readable capability、route、API、job、Provider、Connector、Pack 與 claim inventory。
2. 凍結正式環境精確 release 與 runtime capability digest。
3. 對照 README、`OPEN_GATES.md`、P0–P8、Input I9、KQ0–KQ7 與正式 UI。
4. 將所有能力轉為 R0–R5＋PASS/HOLD/FAIL/NOT RUN/WAIVED/UNVERIFIED。
5. 建立初始 defect／contradiction register。
6. 進行 PRA0 Code Review／Evidence Review；未通過不得進 PRA1。

PRA0 不應干擾李永仁第二輪測試資料，也不應在尚未取得證據時變更 production feature flag。

---

## 19. 參考文件

- `README.md`
- `docs/OPEN_GATES.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/INTERNAL_PRODUCTIZATION_COMPLETION_PLAN.md`
- `docs/INPUT_I9_FIRST_TENANT_PRODUCTION_HARDENING.md`
- `docs/INPUT_I9_SECOND_TENANT_FINAL_ACCEPTANCE_2026-09-03.md`
- `docs/KNOWLEDGE_ANSWER_RELIABILITY_TASK_PLAN_2026-09-03.md`
- `docs/knowledge/PHASE_KQ7_CODE_REVIEW_2026-09-03.md`
- `docs/APPLICATION_DECOUPLING_IMPLEMENTATION_PLAN_2026-08-29.md`
- `docs/PHASE_APPLICATION_A8_PHYSICAL_REMOVAL_FINAL_CODE_REVIEW_2026-08-29.md`
- `docs/APPLICATION_LAYER_ZERO_BASE_PORTFOLIO_REVIEW_2026-08-29.md`
- `docs/SCENARIO_APPLICATION_ZERO_BASELINE_2026-08-29.md`
- `docs/CAPABILITY_CLAIMS.md`
- `docs/PLAN_PROGRESS.md`
- `docs/reports/P6_UIUX_DEVICE_CODE_REVIEW_2026-08-28.md`
- `docs/runbooks/SAAS_TENANT_ONBOARDING.md`
- `docs/runbooks/DATA_DELETION_AND_EXPORT.md`
- `docs/runbooks/PILOT_SUPPORT.md`
- `docs/runbooks/RLS_AUTHORITY_ROLLOUT.md`

---

## 20. 版本紀錄

| 版本 | 日期 | 內容 |
|---|---|---|
| 1.0 | 2026-09-03 | 建立全產品 Reality 等級、稽核範圍、七條端到端旅程、PRA0–PRA9、證據格式、缺陷分級、目前基線與最終完成定義。 |
| 1.1 | 2026-09-03 | 複檢修訂：禁止歷史 R3 自動繼承、分離 Application Pack 與 Knowledge contribution、加入內外雙軌證據、公開網站／API／部署稽核、J08 升級回滾旅程、補強 evidence schema、校正目前基線並登錄已確認的文件漂移。 |
