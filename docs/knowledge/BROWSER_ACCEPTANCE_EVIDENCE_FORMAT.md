# KB-UX-01 瀏覽器驗收證據格式

`scripts/eval_browser_acceptance_gate.py` 只驗證獨立 QA、產品負責人或外部測試者產生的逐案例證據，不代替瀏覽器操作，也不允許開發者自行把空白結果標成通過。

輸入 JSON 必須包含：

- `runner`: `id`、`role`、`independent_of_implementation: true` 與獨立驗收聲明的 `attestation_sha256`；role 僅接受 `qa`、`product_owner`、`external_tester`。
- `image_digest`: 實測 backend 映像的 `sha256:<64 hex>`。
- `frontend_image_digest`: 實測 frontend 映像的 `sha256:<64 hex>`。
- `deployment_manifest_id`: 同時凍結 backend、frontend 與 gateway 輸入的 `dm-<24 hex>`；發布時必須與 Shadow runtime manifest 完全相同。
- `revision_id`、`manifest_hash`: 實際驗收的 immutable KB revision。
- `personas`: `sales`、`field`、`master`、`newcomer`、`viewer`、`admin` 六組逐流程；每筆 PASS 必須含 `{name,status,evidence_refs}`，證據引用可指向 screenshot、video 或 browser trace。
- `negative_controls`: deny、跨租戶、跨部門與 KB membership 衝突。
- `pairwise`: `system_role`、`job_role`、`department`、`kb_membership`、`source_acl` 的 10 組維度配對都必須至少一個可追查 PASS 案例，不得含 skipped／blocked。
- `surfaces`: 來源展開、重新整理、返回、空狀態、403、404、手機、多輪、數字保存與管理員發布判讀。

範例命令：

```powershell
python scripts/eval_browser_acceptance_gate.py `
  --tenant-id <tenant-uuid> `
  --revision-id <kb-revision-uuid> `
  --evidence <independent-browser-run.json>
```

輸出的 `browser_acceptance_last_run.json` 會綁定 exact revision、manifest hash、image digest 與輸入證據 SHA-256；任一必要流程未明確 PASS 時，閘門為 FAIL。
