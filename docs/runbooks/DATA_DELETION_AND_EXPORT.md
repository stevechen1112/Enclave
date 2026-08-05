# 資料刪除與匯出 Runbook（WS-DATA-RESIDENCY）

**產品**：Enclave  
**最後更新**：2026-08-05  
**對齊**：`CLOUD_AND_COMMERCIALIZATION_PLAN.md` §5.9；`docs/legal/DPA_TEMPLATE.md`

> 本 runbook 描述**營運流程**。完整租戶級異步 export API／硬刪工作流若尚未掛載，不得宣稱「一鍵 GDPR 完成」。

---

## 1. 匯出（攜出）

### 1.1 範圍

| 資料 | 來源 | 備註 |
|------|------|------|
| 文件 bytes | `STORAGE_BACKEND`（local／S3） | 依 `documents.file_path` |
| 文件 meta | `documents`／chunks／artifacts | 脫敏：勿含他租戶 |
| 用量 | `usagerecords`／`billing_records` | 依期間篩選 |
| 稽核 | `audit_logs` | 可選；含個資時需 Customer 書面 |

### 1.2 現行手動步驟（Phase 1）

```bash
# 1) 備份 DB（含該租戶列）
python scripts/ops_lifecycle.py backup

# 2) 物件：若為 S3，以租戶前綴同步
# aws s3 sync s3://$S3_BUCKET/<tenant_id>/ ./export/<tenant_id>/files/

# 3) 產出清單與雜湊 → artifacts/ops/export_<tenant>_<ts>/
```

驗收：Customer 可開啟至少一份檔案；meta CSV／JSON 列數與 DB 一致。

### 1.3 目標 API（後續）

`POST /api/v1/company/export`（owner）→ 異步任務 → 預簽名下載 URL；完成寫稽核 `data_export`。

---

## 2. 刪除權（硬刪）

### 2.1 原則

1. **tombstone 先於硬刪**：先 `tombstoned_at`，檢索立即不可見。  
2. **保留期**：預設 30 日（合約可覆寫），期滿後刪物件＋DB 列＋向量。  
3. **證明報告**：寫入 `artifacts/ops/deletion_<tenant>_<ts>.json`（含雜湊與執行者）。

### 2.2 現行步驟

```bash
# 停用租戶（禁止新寫入）
# 管理後台或 SQL：UPDATE tenants SET status='suspended' WHERE id='...'

# 撤銷檢索投影
# 既有 DocumentRevocationService／outbox revoke 路徑

# 期滿後：刪 S3 前綴 + DB CASCADE（需批准閘門）
```

**破壞性操作**（刪 bucket 前綴、drop 租戶）屬 WS-AGENTIC-OPS：**必須人類批准**後才執行。

### 2.3 驗收

- 刪除後：該租戶 chat／search 0 命中。  
- 物件 `exists(key)` 為 false。  
- 證明報告已歸檔並通知 Customer。

---

## 3. 備份／DR（Phase 1 目標）

| 指標 | 目標 |
|------|------|
| RPO | ≤ 24h |
| RTO | ≤ 8h |
| 演練 | 每季一次 restore drill → `HG-DR-SIGN` |

```bash
python scripts/ops_lifecycle.py backup
# restore：見 PILOT_SUPPORT.md／MANAGED_PRIVATE_CLOUD.md
```

---

## 4. 人工閘門

| ID | 項目 |
|----|------|
| HG-LEGAL | DPA 正式簽署 |
| HG-DR-SIGN | 客戶現場還原簽核 |
| HG-PENTEST-CLOUD | 託管環境滲透 |
