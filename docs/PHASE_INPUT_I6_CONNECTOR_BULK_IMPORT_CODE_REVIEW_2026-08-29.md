# Input I6 Connector 與大量匯入 Code Review（2026-08-29）

結論：**INTERNAL ENGINEERING PASS；客戶雲端 Connector 認證待憑證；准入 Input I7。**

## Review identity

- Baseline commit：`d85b1503e1058ec4865d3f21a4477a363205c351`，本階段位於保留既有 I0–I5 變更的 dirty worktree，未建立誤導性的 release commit。
- Schema head：`input_i6_connector_batch_001`。
- Route contract：8 routes，SHA-256 `5af2bf671476e71a40b148d374217000cf5271c648b6a96e7632e5ddb525b69f`（`scripts.release_identity.route_contract`）。
- Runtime／部署：只做本機工程驗證，未部署生產。

## 交付與判定

- NAS/SMB 掃描現在產生 deterministic snapshot/cursor，明確區分完整快照與被 `max_files` 截斷的 partial snapshot；只有完整快照能觸發 rename/delete tombstone。
- Connector SDK 提供 discover/fetch 資源契約、checksum/cursor/ACL/delete semantics，以及有上限的 rate-limit retry 與單次 credential refresh。
- Connector resource 先建立 canonical `SourceAsset` / immutable `AssetRevision`，`Document` 只保留為 parser compatibility bridge；同內容重放不新增 revision，內容變更建立 superseding revision。
- `ImportBatch` / `ImportBatchItem` 保存資料夾階層、共同 metadata、逐檔結果、attempt/error 與 canonical lineage；API 可讀批次並只重試 failed items。
- 完整 ACL snapshot 使用 replacement semantics；消失的 allow entry 會撤銷，partial snapshot 不撤銷。批次、資產與 revision 關聯以 tenant-composite FK 防止跨租戶 lineage。
- Source delete 只 tombstone，不做不可逆刪除；同一 Connector 同步以 DB row lock 序列化。

## Review 發現與修正

1. **High — partial page 可能被當完整清單而誤刪。** 改為只有 `snapshot_complete=true` 且 `delete_semantics=tombstone` 才做 lifecycle reconciliation；空的完整快照仍具有明確刪除語意。
2. **High — ACL 只 upsert 會保留已撤銷權限。** 新增 complete-snapshot replacement，且僅處理明確列入 snapshot 的 source records，避免回應異常時擴權或清空無關 ACL。
3. **High — batch lineage 原先若只用單欄 FK，資料庫不能證明同租戶。** 改為 tenant+batch、tenant+asset、tenant+asset+revision composite FK。
4. **High — Connector 仍以 Legacy Document 建立 canonical identity。** 改為 canonical-first，Document 僅承接既有解析 worker；內容更新不再建立衝突的第二個 active Document。
5. **Medium — connector lifecycle 查詢只按 connector type，兩個 NAS instance 可能互相處理。** 生產 `run_sync` 以 `ConnectorResource` 範圍限制文件；保留沒有 resource rows 的 pre-I6 direct-call compatibility path。
6. **Medium — 並行 sync 可產生重複 canonical identity。** `run_sync` 對 connector row 加 transaction lock，將同一 instance 的 sync 序列化。

## 驗證證據

- I6/connector/legacy lifecycle focused：24 passed。
- Connector + canonical asset + tenant boundary + ACL/outbox related：55 passed。
- Ruff（I6 Python、migration、tests、script）：PASS。
- `compileall app`：PASS。
- `git diff --check`：PASS（只出現既有 CRLF 提示）。
- Alembic：隔離 PostgreSQL/pgvector 容器 fresh upgrade to head → downgrade I5 → re-upgrade I6：PASS，容器已移除。
- Large-tree acceptance：1000 files；完整快照、相同內容重放 cursor/snapshot 相等、rename/delete 改變 snapshot：PASS；報告 `artifacts/input/i6_connector_report.json`。

## 外部證據與 claim boundary

- SharePoint tenant/ACL：`PENDING_CREDENTIALS`。
- Google Drive tenant/ACL：`PENDING_CREDENTIALS`。
- NAS/SMB local deterministic profile：PASS。
- 目前不可宣稱 SharePoint/Google Drive 客戶環境已認證；取得合法客戶 sandbox、OAuth credentials 與資料處理同意後才可把狀態從 B/PENDING 改為 certified。

## Review gate

- Replay without duplicate：PASS。
- Source deletion 不做 irreversible delete：PASS。
- ACL 不放寬且 permission drift 可撤銷：PASS。
- Migration/rollback：PASS。
- Customer cloud sandbox：PENDING，不阻擋 I7 內部工程，但阻擋相應商用認證宣稱。

因此 Input I6 內部工程 gate 通過，准入 Input I7。

## I8 獨立審查補強（2026-08-29）

I8 的跨階段 tenancy review 發現 `import_batches`／`import_batch_items` migration 漏加資料庫層 RLS。此項被列為 P0 並在結案前修正：兩表現在均建立 `tenant_isolation` policy，且 `RLS_ENFORCEMENT_ENABLED=true` 時 FORCE RLS。隔離 pgvector/PostgreSQL 檢查確認 2/2 enabled、forced、policy present；I6–I8 相關 124 項回歸通過。原有 internal engineering 結論維持，並以補強後 migration 為權威版本。
