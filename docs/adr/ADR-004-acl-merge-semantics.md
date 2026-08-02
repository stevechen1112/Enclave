# ADR-004：來源 ACL 與 Enclave RBAC 合併語意

**狀態**：已接受
**日期**：2026-07-31
**決策者**：Enclave 技術團隊

---

## 背景

PipesHub 整合後，Enclave 需要同時處理兩種授權來源：
1. **Enclave 自有 RBAC**：5 級角色（owner/admin/hr/employee/viewer）、部門樹、功能權限、功能旗標
2. **來源系統 ACL**：Google Drive / SharePoint / Confluence 等外部系統的權限（使用者/群組/網域）

需要定義兩者合併的語意，避免授權漏洞。

## 決策

**採用 deny precedence 交集模型：ALLOW = Enclave RBAC ALLOW ∧ Source ACL ALLOW（若存在）。**

### 有效權限公式

```text
ALLOW =
  tenant_match
  AND kb_policy_allows
  AND department_policy_allows
  AND source_acl_allows_if_present
  AND resource_not_tombstoned
  AND policy_revision_is_current
```

### 關鍵語意

1. **來源 ACL 為附加限制，非替代**：即使來源 ACL 允許，Enclave RBAC 不允許則拒絕。
2. **來源 ACL 不存在時不拒絕**：若文件無來源 ACL（如直接上傳到 Enclave），僅依 Enclave RBAC 判斷。
3. **Deny 優先**：任一層拒絕即拒絕。不支援「來源 ACL deny 但 Enclave RBAC allow」的覆蓋。
4. **群組映射**：外部群組/網域需映射到 Enclave 內部 principal，不在查詢時動態解析外部目錄。

## 理由

1. **安全保守性**：交集模型最安全，不會因來源 ACL 寬鬆而繞過 Enclave 政策。
2. **可解釋性**：客戶稽核時可明確指出「此使用者因 Enclave 角色 X 或來源 ACL Y 而被拒絕」。
3. **實作簡單**：不需要衝突解決邏輯（如「哪個 ACL 優先」）。

## 後果

- 需要維護 `external_principals` 映射表。
- 來源 ACL 變更需同步更新 Enclave 的 policy revision。
- 若來源 ACL 比 Enclave RBAC 更嚴格，使用者可能看到比預期更少的內容（需在 UI 說明）。
