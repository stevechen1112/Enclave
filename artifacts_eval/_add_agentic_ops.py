"""Add AI-agent fleet ops revision to cloud plan (2026-08-04 user feedback)."""
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "docs" / "CLOUD_AND_COMMERCIALIZATION_PLAN.md"
text = path.read_text(encoding="utf-8")

# 1. WS-GTM-OPS: upgrade ops model to agentic
old = """### 5.10 WS-GTM-OPS — 開戶、導入、支援

**目標**：可賣、可交、可養。

1. 平台後台：開租戶／設方案／重設配額／模擬登入（審計）。  
2. Onboarding wizard：公司→邀請→首批上傳→（可選）SSO→驗收題。  
3. Sales-Led runbook：POC 14 天檢查清單（含盲測 10 題客製）。  
4. 狀態頁＋事件通報；客服角色權限（只讀稽核）。"""
new = """### 5.10 WS-GTM-OPS — 開戶、導入、支援

**目標**：可賣、可交、可養。

1. 平台後台：開租戶／設方案／重設配額／模擬登入（審計）。  
2. Onboarding wizard：公司→邀請→首批上傳→（可選）SSO→驗收題。  
3. Sales-Led runbook：POC 14 天檢查清單（含盲測 10 題客製）。  
4. 狀態頁＋事件通報；客服角色權限（只讀稽核）。

### 5.10a WS-AGENTIC-OPS — AI Agent 車隊維運（2026-08-04 新增）

**背景**：形態 B 的代價是「客戶數＝系統數」。傳統解法（腳本＋值班人力）在 AI agent 時代已過時——維運勞動本身應由 agent 執行，人類只批准例外。Enclave 自身即為 AI agent 產品，車隊維運是最佳 dogfooding 場景。

**模式**：每個客戶實例的監控、更新、故障處理、開通由維運 agent 執行；**人類只在例外時介入**（agent 處理失敗、破壞性操作、客戶溝通）。

| 維運情境 | Agent 行為 | 人類介入點 |
|----------|-----------|-----------|
| 實例故障 | 診斷→重啟／修復→驗證→寫事件報告 | agent 修復失敗時升級 |
| 版本更新 | 批次更新→跑回歸閘門→失敗自動回滾 | 閘門紅燈時批准例外 |
| 新客戶開通 | 全自動拉起實例＋煙霧測試 | 「確認交付」按鈕 |
| 容量／成本 | 預測→擴容→記帳 | 超過預算閾值時批准 |

**護欄（必要）**：agent 對生產實例的破壞性操作需批准閘門（借用 Enclave 既有 review queue 模式）；全部操作寫稽核軌跡；回滾路徑永遠先於執行路徑就緒。

**效果**：B 形態可維持客戶數從「數十」提升至「數百」；維運人力不隨客戶數線性增長。

**不改變的事**：每客戶基礎設施成本仍在（B 定價須涵蓋）；C 形態的隔離驗證（滲透／紅隊）仍需日曆時間與第三方，agent 只能加速工程不能加速信任。"""
assert old in text
text = text.replace(old, new)

# 2. D1 recommendation: C starts now, not after B sells
old2 = "| D1 | 首發雲形態 | 僅 B / B+C 平行 / 直接 C | **B 主推，C 平行研發** |"
new2 = "| D1 | 首發雲形態 | 僅 B / B+C 平行 / 直接 C | **B 主推銷售；C 隔離工程由 AI agent 立即動工**（真平行，不等 B 賣完） |"
assert old2 in text
text = text.replace(old2, new2)

# 3. Phase 1 exit: ops automation -> agentic
old3 = "- [ ] 可用「一鍵／半自動」為新客戶拉起專屬實例（IaC 或經證實的 SOP）  "
new3 = "- [ ] 新客戶實例由維運 agent 全自動拉起＋煙霧測試，人類僅按「確認交付」（WS-AGENTIC-OPS）  "
assert old3 in text
text = text.replace(old3, new3)

# 4. Risk register: add agentic ops risk
old4 = "| R9 | 形態 C 容量不足（DB 連線／RAGFlow 序列化／LLM 額度） | 高 | WS-CAPACITY 六項工程；CG-CAPACITY 未過不得對 C 形態招商 |"
new4 = old4 + "\n| R10 | 維運 agent 對生產實例誤操作 | 高 | 破壞性操作批准閘門＋完整稽核＋回滾優先（WS-AGENTIC-OPS 護欄） |"
assert old4 in text
text = text.replace(old4, new4)

path.write_text(text, encoding="utf-8")
print("agentic ops added, lines:", len(text.splitlines()))
