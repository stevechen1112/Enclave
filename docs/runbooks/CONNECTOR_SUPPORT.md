# Connector Support Runbook

**適用**：Enclave Enterprise Connect Pack  
**最後更新**：2026-08-01

## 認證狀態

| Connector | 狀態 | 說明 |
|-----------|------|------|
| nas_smb | **認證通過（本機）** | `python scripts/certify_connector.py --type nas_smb` |
| sharepoint | Schema + OAuth URL 就緒 | 需真實 Azure App 憑證（人工） |
| google_drive | Schema + OAuth URL 就緒 | 需真實 Google OAuth 憑證（人工） |

## 測試帳號策略

- NAS：使用唯讀服務帳號對應 `principal_external_id`；禁止用個人管理員帳號當同步帳號。
- SharePoint / Drive：使用最小權限 App（Files.Read.All / Sites.Read.All）；credential 存 vault/`credential_ref`。
- 輪替：`POST /connectors/{id}/credentials/rotate`；輪替後強制 sync。

## 常見故障

1. **sync error `nas_root_not_found`**：檢查 `root_path` 與容器掛載。
2. **ACL 抽樣為空**：確認 sync 時有 `uploaded_by` 映射；來源無 principal → fail-closed。
3. **重複文件**：同一 `source_record_id` + `content_hash` 應去重；見 `materialize_to_documents`。
4. **刪除未收斂**：sync 會 `reconcile_deletes_and_renames`；Gateway deny-set 立即生效。

## 支援指令

```bash
python scripts/certify_connector.py --type all
curl -X POST /api/v1/connectors/{id}/sync
curl /api/v1/connectors/{id}/status
curl /api/v1/connectors/acl/sample/{source_record_id}
```
