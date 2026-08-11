# MKA UX 測試資料總清單

**版本**：1.1 ｜ **建立日期**：2026-08-06
**對應文件**：`docs/MKA_UX_TEST_SCRIPTS.md` v2.0 §7

## 測試環境啟動（真實測試前必讀）

本次 E2E 發現：**Docker 版 worker（enclave-worker-1）讀不到主機 API 寫入的 Windows 路徑**，且 Docker 版前後端（3001/8011）是舊碼。真實測試請用主機版全棧：

| 元件 | 啟動方式 | 位址 |
|------|----------|------|
| API | `cd Enclave && python -m uvicorn app.main:app --host 127.0.0.1 --port 8005` | http://127.0.0.1:8005 |
| Worker | `cd Enclave && python -m celery -A app.celery_app worker --pool=solo` | （redis://localhost:6380） |
| 前端 | `cd Enclave/frontend && npm run dev` | http://localhost:3000 |

- **保持 `enclave-worker-1` 容器停止**（`docker stop enclave-worker-1`），否則它會搶任務且必敗。
- `.env` 已修正：`RAGFLOW_FORCE_PARSE=false`、`PARSER_CANARY=`（原設定是盲測專用，會把 .md 全送去 RAGFlow 導致入庫失敗）。盲測腳本需要時會自行設定。

## 測試帳號（Demo Tenant，密碼皆為 `Demo12345`）

| 帳號 | 系統角色 | 職能（JobRole） | 對應劇本 |
|------|----------|----------------|----------|
| admin@example.com | owner（superuser，密碼 admin123） | — | 主管審核／管理 |
| sales@demo.mka | employee | sales 業務 | 劇本 A |
| field@demo.mka | employee | equipment 設備 | 劇本 B |
| master@demo.mka | employee | supervisor 班長 | 劇本 C（師傅） |
| newcomer@demo.mka | employee | newcomer 新人 | 劇本 C（新人） |
| viewer@demo.mka | viewer | — | 權限邊界測試 |

## 程式化 E2E（已通過 26/26，2026-08-06）

```bash
cd Enclave
python test-materials/e2e/setup_test_env.py   # 建帳號/職能/場景/版型（一次性）
python test-materials/e2e/ingest_docs.py      # 批次入庫 22 份文件
python test-materials/e2e/e2e_walkthrough.py  # 三劇本走查 → e2e_report.json
```

涵蓋：A2 版本差異問答、A3–A5 報價建單→送審→核准→DOCX 匯出（公司版型）、B1 掃碼場景（含未註冊 QR fail-closed）、B2 場景限定問答、B3 異常回報、B4 交接班、C1 訪談建卡、C2 衝突阻擋→處置→送審、C3 核准、C4 新人查詢、P1–P3 權限邊界。

## 虛構世界觀（所有文件共用，務必一致）

| 設定 | 值 |
|------|-----|
| 公司 | 精聯精密工業股份有限公司（虛構） |
| 產品 | P-200 精密張力控制器（版本 v1.0／v2.0／v2.1） |
| 設備 | EQ-100 高速捲繞機（二廠 A 產線） |
| 主要客戶 | 翔展科技（既有客戶）、鼎鈞精密 |
| 測試錨點 | A2 問 v2.0→v2.1 差異（埋 3 處）；A3 報價 300 pcs 落 NT$1,150 級距；B2/B3 用 E-07／E-03；C1/C2 用「目測調張力」舊做法撞 D02 的張力計規定 |

## 一、劇本 A（業務／業務助理）所需文件

| 代號 | 文件 | 位置 | 來源 | 測試用途 |
|------|------|------|------|----------|
| D01a–c | P-200 產品規格書 v1.0／v2.0／v2.1 | `shared/` | 自建（網路僅有空白模板，無法埋版本差異） | A2 版本差異問答 |
| D04 | 價格政策與 MOQ 規則 | `shared/` | 自建（價格政策屬營業秘密，網路無真實件） | A3 級距價／MOQ 帶出 |
| D05a–c | 歷史報價單 ×3 | `A-sales/` | 自建（正式測試時建議換成去敏真實件） | A3 上下文、A4 版型預覽對照 |
| D06 | 外銷客戶規格要求書 | `shared/` | 自建（參考下載的元山科技承認書格式） | A2 進階：客戶要求 vs 版本判斷 |
| T01 | 報價單 DOCX 版型 | `templates/` | 自建（`{{placeholder}}` 語法對齊系統） | A4 版型預覽、A5 匯出 |
| A3 腳本 | 詢價口述 30 秒 | `A-sales/` | 自建（供錄音） | A3 語音輸入 |

## 二、劇本 B（設備與現場人員）所需文件

| 代號 | 文件 | 位置 | 來源 | 測試用途 |
|------|------|------|------|----------|
| D02 | EQ-100 操作與保養 SOP（含 E-01～E-08 異常代碼表） | `B-field/` | 自建（參考勞動部手冊與宜大 CNC 安全標準格式） | B2 場景問答、B3 異常回報依據 |
| D03a–c | EQ-100 維修紀錄 ×3 | `B-field/` | 自建 | B2 追問「最近修過什麼」 |
| D07a | 工具機作業安全作業標準（宜蘭大學） | `_downloads/` | **網路下載** ✅ | 通用安全知識入庫 |
| D07b | EQ-100 安全作業指引 | `B-field/` | 自建（依 D07a 格式改寫為 EQ-100 專用） | B2 安全優先回答 |
| D08 | P-200 成品檢驗規範 | `B-field/` | 自建（參考網路 IQC 規範結構） | 品質相關提問 |
| D11 | 8D 報告範例（P-200 通訊異常） | `shared/` | 自建（對應 D03c 維修紀錄的後續 8D） | 品質模組（quality_8d／capa）內容、8D 問答 |
| T02 | 異常報告 XLSX 版型 | `templates/` | 自建 | B3 送出後匯出 |
| T03 | 交接班紀錄 XLSX 版型 | `templates/` | 自建 | B4 匯出 |
| B3 腳本 | 異常口述 60 秒（含噪音版錄音指引） | `B-field/` | 自建 | B3 語音輸入 |
| QR 資料 | EQ-100 場景註冊資料 | `B-field/` | 自建 | B1 掃碼場景 |

## 三、劇本 C（資深師傅／訓練負責人）所需文件

| 代號 | 文件 | 位置 | 來源 | 測試用途 |
|------|------|------|------|----------|
| D09 | 新人訓練手冊 | `C-knowhow/` | 自建（參考 FDA 訓練 SOP 範本與三級安全教育架構） | C4 新人查詢 |
| D10 | 舊版張力調整作業說明（2019，與 D02 矛盾） | `C-knowhow/` | 自建（**故意埋矛盾**） | C2 SOP 衝突偵測 |
| C1 腳本 | 師傅訪談逐字稿 3–5 分鐘（含眉角＋舊做法） | `C-knowhow/` | 自建（供錄音或直接貼上） | C1 訪談建卡、C2 衝突觸發 |

## 四、網路下載參考件（`_downloads/`）

| 檔案 | 來源 | 可行性評估 |
|------|------|------------|
| D07_工具機作業安全作業標準_宜蘭大學.pdf (378KB) | 宜蘭大學環安衛中心 | ✅ 真實 CNC 安全作業標準，可直接入庫當通用安全知識 |
| ref_機械安全作業標準參考手冊_勞動部.doc (2.2MB) | 勞動部職安署 | ✅ 官方手冊，作為 D07b 改寫依據；也可入庫 |
| ref_機械完整性管理程序參考手冊_勞動部.pdf (396KB) | 勞動部職安署 | ✅ 設備維護管理參考，可入庫當維修管理知識 |
| ref_標準作業程序範本_FDA.doc (456KB) | 衛福部 FDA | ✅ SOP 撰寫架構參考（實為 PDF 格式） |
| ref_產品規格承認書_元山科技.pdf (482KB) | DigiKey 公開文件 | ✅ 台灣真實廠商承認書，D06 格式參考 |

**網路搜尋結論**：SOP／安全標準／承認書／8D／CAPA 的「空白範本與真實格式件」網路充足；但測試需要的 **P-200／EQ-100 具體內容、埋好的版本差異、與 SOP 矛盾的舊文件、語音腳本** 本質上不存在於網路，必須自建。下載件作為格式依據與通用知識入庫，自建件承載測試錨點。

## 五、入庫建議順序

1. `shared/` 全部（D01 三版、D04、D06）
2. `B-field/` 的 D02、D03、D07b、D08
3. `_downloads/` 的 D07a（安全標準）、機械完整性手冊
4. `A-sales/` 的 D05 ×3
5. `C-knowhow/` 的 D09、D10
6. `templates/` 的 T01–T03 上傳至「公司版型」並完成欄位映射、啟用
7. 依 `B-field/QR_場景註冊資料.md` 建立 SceneRegistry 並列印 QR
