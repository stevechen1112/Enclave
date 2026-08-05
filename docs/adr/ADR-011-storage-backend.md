# ADR-011：物件儲存後端抽象（StorageBackend）

**狀態**：已接受
**日期**：2026-08-04
**決策者**：Enclave 技術團隊
**關聯**：`CLOUD_AND_COMMERCIALIZATION_PLAN.md` §5.1（WS-STORAGE）；ADR-003 v2

---

## 背景

Enclave 現將上傳檔案寫入本機磁碟 `UPLOAD_DIR`（依 `tenant_id` 分目錄）。雲端形態（B 託管私有雲／C 多租戶 SaaS）需要物件儲存（R2／S3 相容），但地端形態 A 必須維持本機磁碟（air-gap 客戶無外部連線）。若直接在上傳程式裡寫死 S3 client，地端路徑會被破壞或分叉（風險 R6）。

## 決策

**引入 `StorageBackend` Protocol，所有檔案存取一律經抽象層；部署形態由 `STORAGE_BACKEND` 環境變數決定。**

### 具體措施

1. **介面**：`put / get / delete / exists / presigned_url`（上傳、下載、刪除、存在性、預簽名 URL）。
2. **實作**：
   - `LocalFilesystemBackend`（預設；現行行為，地端與開發用）
   - `S3CompatibleBackend`（R2／Linode Objects／AWS S3／MinIO；雲端形態用）
3. **定址**：DB `documents.file_path` 語意升級為 `content_uri`（`file://...` 或 `s3://bucket/tenant_id/doc_id/...`）；舊值向後相容（無 scheme 視為 local 相對路徑）。
4. **租戶隔離**：S3 相容後端的 key 永遠以 `tenant_id` 為第一段前綴；`delete`／`get` 皆強制帶 tenant 前綴，禁止跨前綴操作。
5. **刪除一致性**：文件撤權／刪除時，物件刪除與 tombstone、向量刪除走同一 outbox 事務邊界（沿用既有 deny-first 不變量）。
6. **Worker**：一律經後端 `get` 到暫存再解析，不直接讀本機路徑（對齊 UniHR `document_tasks` 模式）。

### 明確不做事項

- 不在 Phase 1 做多雲複寫或跨區同步。
- 不引入 Azure Blob（僅預留 Protocol 擴充點）。
- 不改變「文件 bytes 寫入真相在 Enclave 控制的儲存」這一不變量（INV-DATA）——R2/S3 bucket 為 Enclave 自有帳號，非 sidecar、非第三方 SaaS。

## 理由

1. **單一程式碼**：地端與雲端共用同一份上傳／下載邏輯，僅設定不同——消除分叉風險。
2. **可回歸**：local 後端維持現行行為，既有測試與盲測不因抽象層引入而退化。
3. **漸進**：Phase 1 只需 S3 相容一種新後端；MinIO 可作地端企業版的 S3 相容選項（enterprise overlay 已有服務）。

## 後果

- 所有直接操作 `UPLOAD_DIR` 的程式路徑需改經 `StorageBackend`（上傳端點、connector sync、worker 解析、備份腳本）。
- 測試需同時覆蓋 local 與 S3 相容後端（S3 以 moto／MinIO 測試容器）。
- 閘門：`CG-STORAGE`（雙路徑驗收：上傳→入庫→問答→撤權→物件與向量皆不可達；地端切回 local 回歸綠燈）。
