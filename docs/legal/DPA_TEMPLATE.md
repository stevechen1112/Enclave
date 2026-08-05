# Enclave Data Processing Agreement（範本）

**狀態**：草稿（HG-LEGAL 簽核前不可對外宣稱「DPA 可簽」已完成）  
**最後更新**：2026-08-05  
**對齊**：`docs/CLOUD_AND_COMMERCIALIZATION_PLAN.md` §5.9 WS-DATA-RESIDENCY

本 Data Processing Agreement（「DPA」）構成主服務契約、訂單或其它書面協議（合稱「協議」）之一部分，當事人為：

- **Customer（客戶）**：[Customer Legal Name]
- **Processor（處理者）**：Enclave／[Operating Entity Legal Name]

> 本文件為**技術／商務草稿範本**，非正式法律意見。正式對外簽署前須經法務審閱（HG-LEGAL）。

---

## 1. Purpose

本 DPA 規範 Processor 代表 Customer 處理個人資料之範圍，適用於 Enclave 地端自管、託管私有雲與多租戶 SaaS 形態中，由 Customer 上傳或指示處理之個人資料。

## 2. Roles of the Parties

- Customer 為控管者（Controller），或代其控管者行事之處理者。
- Enclave 為處理者（Processor）；若 Customer 本身為處理者，則 Enclave 為次處理者（Sub-processor）。

## 3. Subject Matter and Duration

- **標的**：提供文件管理、知識檢索、問答、租戶治理、身分驗證與支援服務。
- **期間**：協議期間，並依第 10 節刪除或返還個人資料為止。

## 4. Nature and Purpose of Processing

Enclave 得為下列目的處理個人資料：

- 託管與儲存客戶上傳文件與中繼資料；
- 使用者身分驗證與租戶帳號管理；
- 文件解析、檢索、AI 輔助回答與來源稽核；
- 支援、監控、備份、稽核日誌與資安營運；
- 發送交易性電子郵件（邀請、驗證、重設密碼、服務通知）。

## 5. Categories of Personal Data

視客戶使用方式，可能包括：

- 使用者檔案：姓名、工作信箱、部門、角色、登入紀錄；
- 客戶上傳文件中之員工／業務相關內容；
- 使用日誌、IP、裝置／瀏覽器中繼資料、稽核紀錄；
- 支援通訊與管理組態資料。

## 6. Categories of Data Subjects

- 客戶員工、承包商、管理員與授權使用者；
- 出現於上傳文件中之資料主體；
- 計費／技術聯絡人。

## 7. Customer Instructions

Enclave 僅依 Customer 之書面指示處理個人資料（含為履行協議所必需者），法律另有要求除外。

## 8. Processor Obligations

Enclave 應：

- 僅依指示處理；
- 確保接觸人員受保密義務拘束；
- 實施適當技術與組織安全措施；
- 在法律要求且技術可行時協助資料主體請求；
- 知悉影響 Customer 之個人資料侵害事件後，無不當遲延通知 Customer；
- 維護次處理者紀錄，並依契約要求通知重大變更。

## 9. Security Measures

Enclave 安全控制（依形態適用）包括：

- 租戶隔離（應用層 ACL；形態 C 另含 PostgreSQL RLS）；
- RBAC、稽核軌跡、上傳掃毒（ClamAV fail-closed 於雲端形態）；
- 傳輸加密與基礎設施存取控制；
- 備份、監控、告警與事件應變；
- 密鑰／secrets 管理與最小權限。

Customer 知悉任何安全措施無法消除全部風險，並負責正確設定存取控制與僅上傳經授權內容。

## 10. Sub-processors

Enclave 得為基礎設施、物件儲存、郵件、監控與 AI 模型服務使用次處理者。Enclave 應：

- 維持現行次處理者清單（見附錄 A）；
- 以契約約束次處理者負擔不低於本 DPA 之義務；
- 依協議約定通知重大新增／更換。

## 11. International Transfers

若個人資料移轉至 Customer 指定區域以外，應依適用法令採用適當保護機制（標準契約條款、等同措施或客戶書面同意）。形態 B／C 預設**單區域**（Phase 1–2）；多區域屬 Phase 3（CG-REGION）。

## 12. Data Subject Requests / Assistance

Enclave 應在合理範圍內協助 Customer 回應查詢、更正、刪除與可攜請求。租戶級匯出／刪除流程見 `docs/runbooks/DATA_DELETION_AND_EXPORT.md`。

## 13. Return or Deletion

協議終止或 Customer 書面要求後，Enclave 應依指示返還或刪除個人資料（法律要求保留者除外），並得提供刪除證明報告。

## 14. Audit

Customer 得依協議約定，以合理書面通知要求稽核或取得第三方認證摘要。生產環境入侵測試屬 HG-PENTEST／HG-PENTEST-CLOUD 閘門，不得以本範本替代。

## 15. Liability / Precedence

責任上限與優先順序以主協議為準。本 DPA 與主協議衝突時，**個人資料處理條款以本 DPA 為準**。

---

## Appendix A — Sub-processor categories（草稿）

| 類別 | 範例（依部署選擇） | 形態 |
|------|-------------------|------|
| 計算／VM | Linode／同等 | B、C |
| 物件儲存 | Cloudflare R2／Linode Objects | B、C |
| 邊緣／WAF | Cloudflare | B、C |
| LLM／Embedding | OpenAI／Gemini／Voyage 等（Customer 或 Enclave 合約） | B、C |
| 觀測 | Sentry／Langfuse（可選） | B、C |
| 金流 | NewebPay（台灣） | B、C |

## Appendix B — 簽核欄（人工）

| 項目 | 負責人 | 日期 | 簽名 |
|------|--------|------|------|
| 法務審閱（HG-LEGAL） | | | |
| 客戶簽署 | | | |
| Enclave 簽署 | | | |
