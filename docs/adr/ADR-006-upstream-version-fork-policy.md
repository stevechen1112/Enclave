# ADR-006：上游版本、升級與 Fork 政策

**狀態**：已接受
**日期**：2026-07-31
**決策者**：Enclave 技術團隊

---

## 背景

Enclave 依賴三個活躍的開源上游：RAGFlow、PipesHub、WeKnora。需要定義版本鎖定、升級與潛在 Fork 的政策。

## 決策

### 版本鎖定

- 每個 Enclave 發版鎖定上游的 commit hash、Git tag、容器 image digest。
- 禁止在生產環境使用 `latest` tag 或浮動版本。
- 上游版本記錄在 `DEPENDENCIES.md`，包含：
  - 上游名稱、repo URL、commit/tag、image digest
  - 使用的 API 端點與契約版本
  - 已知的 CVE 與修復版本
  - LICENSE 與 NOTICE 檔案路徑

### 升級政策

- 上游升級需經過完整測試（contract + integration + e2e + security）。
- 升級前需檢閱 upstream CHANGELOG、breaking changes、security advisory。
- 升級後需更新 Adapter 契約版本號。
- 支援 N-1 回滾：新版本部署後，保留前一版本的容器映像至少 30 天。
- 重大安全修補（Critical CVE）需在 7 天內評估並部署。

### Fork 政策

- **預設不 Fork**。只在以下情況考慮 Fork：
  1. 上游停止維護（≥6 個月無 commit）
  2. 上游授權變更導致無法商用
  3. 上游拒絕接受關鍵安全修補
  4. 需要的能力無法透過 Adapter 實現
- Fork 前必須有獨立 ADR，包含：
  - Fork 原因與不可逆後果
  - 維護計畫（誰負責追蹤上游、合併變更）
  - 相容性測試與遷移計畫
  - 法律審查（授權相容性）

## 理由

1. **降低維護負擔**：Fork 後需自行維護數十萬行程式碼，成本遠高於 Adapter 維護。
2. **上游演進紅利**：RAGFlow/WeKnora/PipesHub 的社群迭代速度超過任何單一團隊。
3. **授權合規**：Apache 2.0/MIT 允許商用，但 Fork 後需遵守 NOTICE 義務。

## 後果

- 需要定期檢閱上游 release 與 security advisory。
- Adapter 契約可能因上游 breaking change 而需更新。
- 若上游方向與 Enclave 需求偏離，需評估替代方案。
