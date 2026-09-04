---
title: "Enclave 第一租戶 Input、檢索與問答現況實測"
document_type: "product_reality_execution_report"
language: "zh-TW"
date: "2026-09-04"
last_reviewed: "2026-09-04"
production_url: "https://kachu.tw"
tenant: "八策股份有限公司"
test_identity: "李永仁／owner"
status: "EXECUTED / HOLD"
decision: "NOT READY FOR UNSUPERVISED FIRST-TENANT KNOWLEDGE USE"
---

# Enclave 第一租戶 Input、檢索與問答現況實測

## 1. 結論先行

這次不是沿用舊報告，而是於 2026-09-04 直接登入 `https://kachu.tw` 的八策正式企業工作區，以李永仁的 `owner` 身分重新檢查正式環境。

目前可以證明：

- 正式站、TLS、登入、租戶綁定及主要頁面可以運作；
- 五筆真實來源均已收進正式資料庫，原始來源未遺失；
- 音訊、圖片與三支影片都有完成處理器流程並產生衍生資料；
- 正式 Ask API 與主問答模型目前可以回應；
- 系統在證據不足時大致會拒絕直接下結論，而不是捏造明確答案；
- 390×844 的手機瀏覽器模擬中，總覽、資產、人工確認及問答頁均能開啟，未發現水平溢位。

但核心目標「把多元 Input 可靠地變成可搜尋、可引用、可問答的企業知識」目前**尚未成立**：

1. 五筆來源全部 `answer_ready = false`，已發布知識為 0。
2. 問與三支影片標題完全一致的問題時，Ask 沒有找到影片或音檔，反而都取回低品質的 `IMG_8592.jpeg`。
3. Ask 引用的 `IMG_8592.jpeg` 文件頁，自己明確顯示「尚不可問答」及「尚無正式可查內容」。這證明發布真相與實際 serving path 不一致。
4. 122 筆人工候選中有 118 筆低風險項目，並包含 `speaker_turn`、`timeline_alignment`、`video_scene` 等技術結構，人工工作量不合理。
5. 五筆來源都要求另一位 Owner 確認；建立來源的李永仁無法獨立完成發布閉環。
6. 圖片 OCR 平均信心僅 52%，三支影片仍有簡繁混用、逐字稿錯字與未校準信心值。
7. 最新 I10 修正仍只在本機工作區，尚未部署或套用正式資料庫 migration，也尚未重新處理這五筆來源。

因此本輪正式判定為：

> `HOLD`。目前適合由內部團隊進行受控修復及驗收，不適合再對第一租戶宣稱「上傳後即可穩定問答」。

## 2. 本次測試邊界與證據原則

本次把不同層次分開，不再用較低層證據替代較高層結論：

| 層次 | 本次如何驗證 | 結果 |
|---|---|---|
| 正式站與身分 | 正式 URL、真實帳號登入、`/health`、`/users/me`、bootstrap | PASS |
| 收件與機械處理 | 五筆正式來源、revision、job、artifact、時間軸 | PASS |
| 解析內容品質 | OCR／ASR 統計、跨來源比對、可見錯字 | FAIL／NOT EVALUATED |
| 人工確認可用性 | 正式 review inbox、手機頁面、工作量與權責 | FAIL |
| 發布真相 | `answer_ready`、已發布資產、文件生命週期 | FAIL |
| 檢索 | 用來源主題直接提問、核對取回來源 | FAIL |
| 回答忠實性 | 有證據問題與不存在代碼問題 | PARTIAL PASS |
| 精確引用 | 文件、頁碼、圖片區域、時間碼及可開啟證據 | FAIL |
| 全部外部 Provider | 正式即時 probe | NOT RUN／受 IP allowlist 阻擋 |
| 最新未部署程式 | focused regression、前端測試、編譯及靜態檢查 | MIXED |

本報告沒有把 Provider confidence 當成語意正確率，也沒有把「API 回 200」當成使用者工作完成。

## 3. 正式環境身分

本次 `/health` 實測：

| 欄位 | 正式觀察值 |
|---|---|
| HTTP | 200 |
| environment | production |
| database | ready |
| release | `force-rls-7f9416f` |
| source commit | `7f9416f2de59e2bb7d153591b1542e4bdd8e3c1d` |
| deployment manifest | `dm-cedec2c3fec871d62592ff6b` |
| schema head | `tenant_force_rls_pra_002` |
| source dirty | false |

正式帳號實測：

- 登入：HTTP 200；約 408 ms。
- 租戶：八策股份有限公司，tenant ID `74202fed-5090-435a-bc65-c69b630499ec`。
- 角色：`owner`，非平台 superuser。
- 環境標籤：正式企業工作區。
- bootstrap 回傳 `ask`、`browse_knowledge`、`upload_documents`、`manage_sources`、`review_queue` 等能力。
- 密碼僅用於本次執行，未寫入本文件、測試產物或程式碼。

## 4. 五筆真實來源現況

| 來源 | 種類 | 正式資產狀態 | 工作狀態 | 可問答 |
|---|---|---|---|---|
| 人資音檔 | audio | review_required | human_review／review_required | 否 |
| IMG_8592.jpeg | image | **active** | human_review／review_required | 否 |
| 員工自願不保勞保影片 | video | review_required | human_review／review_required | 否 |
| 員工責任制影片 | video | review_required | human_review／review_required | 否 |
| 職場性騷擾影片 | video | review_required | human_review／review_required | 否 |

正式資產清單為 5 筆，`publication_status=published` 為 0 筆。圖片外層資產狀態為 `active`，但 revision／job 與 UI 都是等待人工確認，代表狀態語彙仍不一致。

### 4.1 解析基線

| 來源 | 已產生內容 | 已知品質問題 |
|---|---|---|
| 人資音檔，92.5 秒 | 20 段逐字稿；20/20 有時間碼；尾端覆蓋 98.72% | Provider 未提供 confidence；仍有「人字長／人資長」等錯字；無人工 truth，無法簽發 CER/WER PASS |
| IMG_8592.jpeg | 1 筆整合文字、19 個 OCR region，共 126 字 | 全部 OCR confidence 為 52%；文字明顯破碎；整合文字缺 typed evidence |
| 員工自願不保勞保影片，80.2 秒 | 4 段逐字稿、6 幀、5 OCR、程序候選 | 時間軸 96.41%；OCR 平均 74.68%；程序信心 41.49%；需人工確認 |
| 員工責任制影片，129.8 秒 | 16 段逐字稿、9 幀、8 OCR、程序候選 | 時間軸 97.48%；OCR 平均 85.25%；程序信心 28.42%；簡繁混用明顯 |
| 職場性騷擾影片，80.3 秒 | 6 段逐字稿、6 幀、6 OCR、程序候選 | 時間軸 93.91%；OCR 平均 73.88%；程序信心 36.94%；簡繁混用明顯 |

音檔與「員工自願不保勞保」影片的正規化逐字稿相似度為 97.41%，但兩者仍有「人字長／人資長」「裁發／裁罰」「應付單／應負擔」等差異。相似度只能證明兩路大致一致，不能證明兩者正確。

整批共有 153 筆 artifacts、145 筆 evidence spans；人工候選證據為 121/122，未達必要的 100%。

### 4.2 真實內容人工抽查

本輪另外直接閱讀正式人工確認 API 回傳的候選內容，而不只檢查筆數與 confidence。抽查結果顯示，解析器已有部分語意能力，但還不能把「有抽到文字」等同於「形成可靠知識」。

| 來源 | 有價值的解析結果 | 仍存在的問題 | 判定 |
|---|---|---|---|
| 員工自願不保勞保影片 | 候選內容有抓到員工不能任意要求不投保、雇主不能直接答應，以及雇主法定責任等核心意思 | 逐字稿仍有「人字長／人資長」「裁發／裁罰」「應付單／應負擔」等錯字；一段宣導說明被包裝成低信心 `procedure_candidate` | 語意部分可用，但須人工校正及重新建模 |
| 員工責任制影片 | 候選內容有抓到《勞動基準法》第 84-1 條、指定工作者、書面約定及主管機關核備等條件，也有辨識「責任制不等於沒有加班費」 | 逐字稿有大量簡體字與人名／詞語誤辨；程序信心僅 28.42%；宣導內容被切成細碎步驟 | 關鍵規則可見，但尚不可自動發布 |
| 職場性騷擾影片 | 有辨識到職場性騷擾不只包含肢體行為，亦可能包含言語或其他越界行為 | 逐字稿簡繁混用；OCR 可見破碎字串及畫面裝飾文字；程序信心僅 36.94% | 主題有抓到，細節與結構不足 |
| IMG_8592.jpeg | 產生 19 個 OCR 區域及一份整合文字 | 整合結果包含明顯無意義字串與錯誤拉丁字元，版面閱讀順序不穩；全部區域 confidence 固定為 52% | 不足以支援可靠摘要或問答 |

這代表目前品質問題有三個層次：

1. **文字層**：錯字、簡繁混用、OCR 雜訊及閱讀順序錯誤。
2. **知識結構層**：系統會把教育宣導或法規說明泛化成「程序」，沒有先判斷它是規則、解說、案例或真正 SOP。
3. **產品閉環層**：即使候選內容含有可用語意，也沒有經過合理確認、正式發布、建立檢索索引並回到精確時間碼，所以使用者仍問不到。

因此較準確的產品結論是：**多模態解析已有可見的語意雛形，但品質、類型判斷、人工確認與 serving 尚未連成可泛化的企業知識能力。**

## 5. 人工確認旅程

正式 API 與手機頁面一致顯示：

- 5 個來源；
- 122 筆候選內容；
- 高風險 3 筆；
- 中風險 1 筆；
- 低風險 118 筆；
- 各來源分別有 18、43、21、20、20 筆候選；
- 候選類型包含逐字稿 46、OCR 區域 38、說話者段落 26、程序候選 3、時間軸對齊 3、影片鏡頭 3、動作事件 1、音訊事件 1、整合文字 1；
- 其中 `speaker_turn`、`timeline_alignment`、`video_scene` 共 32 筆只是內部技術結構；
- 122 筆全部被 `separation_of_duty` 阻擋，0 筆可批次處理，另有 1 筆缺少 evidence；
- 建立者不可自行核准，頁面顯示「需由另一位擁有者確認」。

這不是純 UI 文案問題。它造成第一個真實使用者上傳 5 筆後，必須面對 122 筆內容，而且自己無法完成閉環。合理產品行為應改為來源層級確認，並只把真正需要人判斷的程序、規則、例外、風險及低品質文字交給使用者。

## 6. 正式檢索與問答實測

### 6.1 四個有來源主題的問題

| 問題 | Ask | 實際取回來源 | 判定 |
|---|---:|---|---|
| 員工可以自願不參加勞保嗎？公司可以答應嗎？ | 200／約 4.62 秒 | 只有 `IMG_8592.jpeg`，score 0.4246 | FAIL：未取回對應影片或音檔 |
| 員工責任制在什麼情況下才合法？ | 200／約 6.13 秒 | 只有 `IMG_8592.jpeg`，score 0.4888 | FAIL：未取回對應影片 |
| 公司發生職場性騷擾事件時應怎麼處理？ | 200／約 3.74 秒 | 只有 `IMG_8592.jpeg`，score 0.4703 | FAIL：未取回對應影片 |
| IMG_8592.jpeg 的內容重點是什麼？ | 200／約 5.80 秒 | `IMG_8592.jpeg`，score 0.032787 | PARTIAL：找對檔名，但內容品質不足 |

前三題的回答都有明確表示知識不足，沒有憑空給出勞動法結論，這是正面行為；但取回完全不相關的圖片，代表檢索召回失敗。

圖片問題的回答承認文字「嚴重缺漏且排列混亂」，與 52% OCR 基線一致。因此目前最可靠的產品行為其實是拒答，而不是提供可用企業知識。

### 6.2 不存在資料的拒答

使用隨機、確定不存在的內部代碼提問：

- API 200，約 6.50 秒；
- 回答明確表示沒有足夠文件，沒有捏造該代碼的 SOP；
- 但仍附上 `IMG_8592.jpeg` 作為來源，score 0.4251。

結論：拒答文字 PASS，但檢索閾值／來源附掛 FAIL。沒有證據時不應把無關來源包裝成答案證據。

### 6.3 發布真相與 Ask serving path 衝突

這是本次最高嚴重度發現：

1. 資產 API：五筆全部 `answer_ready=false`。
2. 已發布資產查詢：0 筆。
3. `IMG_8592.jpeg` 的文件頁：明確顯示「尚不可問答」「尚無正式可查內容」。
4. Ask：仍把這筆圖片的 legacy document projection 當成來源。

因此目前至少存在兩套互相不一致的真相來源：新版資產／Knowledge Unit 生命週期與 Ask 的 legacy／shadow read path。這不修正，就不能宣稱「只有經人工確認與發布的知識才會被 AI 使用」。

### 6.4 引用品質

Ask 回傳的來源具有 `document_id`，前端能開啟文件頁；但本輪所有來源都沒有：

- `citation_id`；
- `evidence_url`；
- 頁碼；
- OCR bounding box；
- 影片時間碼；
- 關鍵幀定位。

所以目前只能追到一個文件頁，而且該頁還標示尚不可問答；尚未達到「答案可回到原始檔案中的精確證據位置」。

## 7. UI／瀏覽器實測

### 7.1 手機 390×844

使用李永仁帳號、單一登入 session 依序檢查：

| 頁面 | 結果 | 約略載入時間 | 水平溢位 |
|---|---|---:|---|
| 登入後總覽 | PASS | 0.48 秒登入；頁面 1.31 秒 | 無 |
| 所有資產 | PASS | 1.12 秒 | 無 |
| 人工確認 | PASS | 1.24 秒 | 無 |
| 問答 | PASS | 1.08 秒 | 無 |

總覽已如實顯示「全部來源 5、已可問答 0、等待人工確認 5、122 筆候選內容」，比先前的「可使用 2」狀態清楚。

### 7.2 桌面 Playwright 現行契約

正式站 `core-flows.spec.ts`：5/10 通過。

通過項目：

- 登入頁錯誤帳密提示；
- 未登入存取資產頁會導回登入；
- 知識導覽可到所有資產；
- 舊 `/documents` 可導向正式資產庫；
- 舊治理網址可導向新網址。

未通過項目需分開解讀：

- 1 項是測試仍期待舊標題「公司知識營運總覽」，正式 UI 已改成「公司知識工作區」；屬測試與產品文案漂移。
- 3 項是測試每個案例都重新登入，快速重複登入後被 production rate limit 擋住，停留在 `/login`。
- 1 項 bootstrap 因相同 rate limit 回 429。

另以單一 session 的自訂手機旅程執行時，登入與四個主要頁面均通過。因此這批失敗不能全部算成功能壞掉，但證明正式 E2E 沒有針對 rate limit 設計共享 session／合理速率，且現有測試已出現文案漂移。

### 7.3 瀏覽器工具邊界

本工作階段的內建可控瀏覽器回報 unavailable，因此改以 repository 既有 Playwright／Chromium 對正式站執行。沒有把 HTTP 或後端結果冒充成人工可見 UI 證據。

## 8. Provider 現況

### 8.1 正式環境已實際證明

- 李永仁帳號 5 次 Ask 均得到 HTTP 200，約 3.74～6.50 秒，證明正式主問答模型目前可被呼叫。
- Demo 租戶的 P-100 問題能正確回答標準單價 120 元、500 件 5% 折扣及折後 114 元，並引用正確 Demo 文件，證明正式主問答＋合成文件檢索路徑仍可運作。
- Demo 不存在代碼測試會明確拒答；但仍會附上語意相近但無法支持該代碼的來源，顯示來源閾值仍需修正。

### 8.2 本次不能重新證明

使用八策 Owner 呼叫正式 Provider configuration／probe 均回 403：`Access denied: IP not in admin whitelist`。因此本次不能對目前 release 重新簽發以下 7/7 證據：

- 主問答 LLM；
- 內部分類 LLM；
- 掃描理解 LLM；
- embedding；
- 短語音 TTS→STT；
- 長音檔與說話者辨識；
- Cloud OCR。

正式 Ask 已直接證明主問答可用，但其他能力只能引用過去 release 的歷史證據，不得算成目前 release PASS。

本機 Provider probe 為 1/7：OpenAI 主問答通過；本機缺少資料庫後退到 `nogpu` profile，Ollama 無法連線，voice／long audio／Cloud OCR 在本機設定為未啟用。這是本機驗收環境不完整，不等於正式站 6 個 Provider 都故障；同時也表示目前無法在開發機重現 production provider matrix。

## 9. 最新未部署程式的工程驗證

### 9.1 通過

- Input／檢索／問答 focused backend regression：123 passed。
- Frontend Vitest：41 個檔案、139 tests passed。
- TypeScript：PASS。
- Vite production build：PASS，3,259 modules transformed。
- Alembic 僅有一個 head：`input_i10_confidence_001`。
- `git diff --check` 沒有 whitespace error。

### 9.2 未通過或未完成

- Frontend ESLint：42 errors，主要為 React effect 內同步更新 state、舊 memoization contract 及宣告順序問題。
- I10 相關檔案的 focused Ruff：1 個 unused import；11 個檔案不符合目前 formatter。
- 全庫 Ruff 存在大量歷史技術債，不能宣稱 repository lint clean。
- `alembic check`：本機 PostgreSQL `localhost:5435` 未啟動，無法執行。
- 後端全量 1,755 tests 曾啟動並執行至約 48%；大量需要 PostgreSQL 的案例在共同 fixture 階段出現 `connection refused`。由於後續結果會持續重複相同基礎設施錯誤，本輪中止全量執行，不能記為全量 PASS，也不把所有 fixture error 誤列為產品 regression。與本次 Input／檢索／問答直接相關且可在現況執行的 focused 123 tests 已全部通過。
- 正式 PostgreSQL migration、N-1 相容性、正式重處理及 rollback gate：NOT RUN。
- 最新程式仍在 dirty working tree；正式站仍是舊 release。

最新本機變更相較 production source 的可見差異至少涉及 22 個 Input／前端／測試檔案、約 1,913 additions／278 deletions；整個工作區共有 114 筆 modified／deleted／untracked 狀態，包含程式、文件及測試產物。部署前必須先建立乾淨 release input，不能直接從目前 dirty tree 發布。

## 10. 缺陷清單與優先順序

| ID | 嚴重度 | 缺陷 | 目前影響 | 必要關閉條件 |
|---|---:|---|---|---|
| RTA-001 | Critical | Ask 使用「尚不可問答」的 legacy document | 未確認／未發布內容仍可能影響回答 | Ask 只讀 active release 的 answer-ready unit；撤權後立即不可查；production E2E PASS |
| RTA-002 | Critical | 影片／音檔完全沒有進入本輪檢索 | 使用者上傳的核心媒體無法被問到 | 每種媒體完成發布→檢索→回答→精確引用 |
| RTA-003 | High | 無關圖片被附掛為三個影片問題與不存在代碼的證據 | 回答雖拒答，證據仍誤導 | relevance floor、來源支持性 Gate、無證據時 sources 應為空或清楚標成僅供探索 |
| RTA-004 | High | 122 筆人工候選含 32 筆技術結構 | 第一租戶無法合理完成確認 | 技術 artifacts 移出人工佇列；來源層級確認；人工負荷驗收 |
| RTA-005 | High | 建立者對所有風險均被 separation-of-duty 阻擋 | 兩人公司仍無法順利完成知識發布 | 低風險原文與高風險推論採不同規則；雙 Owner 實際閉環 PASS |
| RTA-006 | High | OCR／ASR 尚無人工 ground truth | 無法證明語意正確率 | 建立 truth corpus；CER/WER、關鍵欄位、時間碼 P95 達標 |
| RTA-007 | High | 最新 I10 修正尚未部署／重處理 | 正式站仍保留已知舊缺陷 | 乾淨 release、migration、reprocess、差異報告、rollback gate |
| RTA-008 | Medium | 資產 `active`、job `review_required`、UI「等待人工確認」不一致 | 狀態難理解，程式可能選錯 serving path | 建立單一 lifecycle truth 並做契約測試 |
| RTA-009 | Medium | 引用缺頁碼／bbox／時間碼 | 無法核對精確證據 | 每種 modality locator coverage 100%；連結可開回正確位置 |
| RTA-010 | Medium | 正式 Provider probe 受 IP allowlist 阻擋 | 無 current-release 7/7 證據 | 從核准 runner 執行並綁定 release identity |
| RTA-011 | Medium | 正式 E2E 與 rate limit／UI 文案漂移 | 測試結果混雜假失敗 | 重用登入 session、遵守速率、更新穩定 semantic locator |
| RTA-012 | Medium | 前後端全庫 lint 不乾淨 | 維護與回歸風險偏高 | 分基線債務與新增差異；新變更零新增 lint；逐批清債 |

## 11. 下一階段驗收順序

不得直接跳到「請李永仁大量複測」。建議依序：

1. 修正 RTA-001：統一 answer-ready 與 Ask serving truth，阻止未發布 legacy projection 被檢索。
2. 修正 RTA-004／005：來源層級確認、技術 artifacts 移出一般待辦、依風險實施職責分離。
3. 完成乾淨 release，於有授權 migration role 的 release 環境執行 `input_i10_confidence_001`。
4. 對五筆來源建立新 revision 或可回滾的重新處理批次；保留舊產物供差異比較。
5. 人工建立最小 truth set：音／影片逐字稿、圖片 OCR、關鍵數字與條件、每題預期來源及拒答條件。
6. 每個來源完成核准與 active Knowledge Unit release。
7. 執行至少以下正式測試：
   - 來源標題直接問；
   - 同義改寫問；
   - 跨來源比較問；
   - 不存在資料拒答；
   - 版本衝突問；
   - 撤權後不可查；
   - 另一租戶不可查；
   - 證據連回頁碼／bbox／時間碼。
8. 從核准網路執行 current-release Provider 7/7 probe。
9. 在 iPhone Safari 與 Android Chrome 真機各跑一次，不只使用 Chromium emulation。
10. 上述 Gate 全部 PASS 後，再交給李永仁進行第二輪大量真實測試。

## 12. 本次測試造成的資料狀態

- 沒有上傳、刪除或重新處理八策的五筆來源。
- 沒有核准、退回或修改任何人工確認項目。
- 沒有變更租戶、角色、權限、Provider 或正式設定。
- 為測試 Ask，以李永仁帳號建立 5 次問答請求；內容均為本報告列出的四個來源主題與一個隨機不存在代碼。
- Demo 租戶另執行合成 P-100 與不存在代碼問答；不涉及八策資料。

## 13. 最終產品判定

| 宣稱 | 本次判定 |
|---|---|
| 正式站可開啟、可登入 | PASS |
| 第一租戶可以上傳並保存多媒體 | PASS（本批 5/5） |
| 處理器能產生衍生資料 | PASS（機械層） |
| 解析內容已證明正確 | HOLD |
| 人工確認流程實用 | FAIL |
| 已確認內容才會被 Ask 使用 | FAIL |
| 音訊／影片可被 Ask 找到 | FAIL |
| 回答具精確可追溯證據 | FAIL |
| current-release 全 Provider 可用 | NOT RUN |
| 可交給第一租戶無人陪同使用 | **NO** |
| 可作為內部受控修復與驗收環境 | **YES** |

本次最重要的產品教訓不是「再多寫幾個單元測試」，而是所有 Ready 宣稱都必須跨越同一條真實閉環：

> 原始來源存在 → 內容解析可對照 → 人員能合理確認 → 正式發布 → Ask 只讀正式發布內容 → 命中正確來源 → 回答忠實 → 可開回精確證據 → 撤權後立即失效。

任一環節尚未通過，產品結論都必須維持 `HOLD`。

## 14. 第二次獨立複核紀錄

2026-09-04 再次以相同正式租戶及 Owner 身分執行唯讀複核，未沿用瀏覽器畫面中的舊計數：

- `/health` 仍為 HTTP 200、production、database ready，release identity 與第 3 節一致；
- 正式資產 API 再次回傳 5 筆，五筆 `answer_ready` 皆為 false；
- `publication_status=published` 的實際回傳為空陣列，確認不是前端篩選造成的 0；
- review API 再次回傳 122 筆，風險、類型、阻擋原因及 evidence 缺口與第 5 節一致；
- JSON 解析稽核重新對帳為 5 個來源、153 個 artifacts、122 個人工候選，overall status 為 `HOLD`；
- 文件未出現重複二級標題、待補標記、電子郵件或密碼字串，`git diff --check` 通過。

第二次複核沒有發現足以推翻原判定的反證；反而確認人工確認工作區目前完全無法批次處理，且每一筆都受職責分離阻擋。因此本報告的產品判定維持 `HOLD`。
