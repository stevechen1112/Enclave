"""Record D1-D7 decisions into cloud plan (2026-08-04)."""
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "docs" / "CLOUD_AND_COMMERCIALIZATION_PLAN.md"
text = path.read_text(encoding="utf-8")

# 1. Update decision table with outcomes
old_table = """| # | 決策 | 選項 | 建議 |
|---|------|------|------|
| D1 | 首發雲形態 | 僅 B / B+C 平行 / 直接 C | **B 主推銷售；C 隔離工程由 AI agent 立即動工**（真平行，不等 B 賣完） |
| D2 | 雲供應商 | CF+R2+Linode / AWS 全家 / GCP | 延續 UniHR 營運經驗可降風險 |
| D3 | 金流 | 僅合約手動 / NewebPay / +Stripe | Phase 1 手動可接受；Phase 2 NewebPay |
| D4 | 向量 | 僅 pgvector / +Pinecone / +Qdrant Cloud | 地端與 B 用 pgvector；C 視規模加託管向量 |
| D5 | 自助註冊時程 | 12 個月內不開 / Phase 2 開 | **12 個月內不開** |
| D6 | enforce 溯源預設 | 全開 / 方案分級 | **方案分級**（Team shadow / Business+ enforce） |
| D7 | 雲端內部模型落點 | Voyage embed＋雲端小模型稽核 / CPU 自跑小模型池 | **雲端 API 優先**（零 GPU 原則一致；地端維持 Ollama） |"""

new_table = """| # | 決策 | 定案（2026-08-04） | 理由 |
|---|------|------|------|
| D1 | 首發雲形態 | ✅ **B 主推銷售；C 隔離工程由 AI agent 立即動工** | 最快變現＋隔離風險最高的部分提前啃 |
| D2 | 雲供應商 | ✅ **Cloudflare＋R2＋Linode** | 延續 UniHR 生產營運經驗，坑已踩過 |
| D3 | 金流 | ✅ **Phase 1 直接接 NewebPay**（不做手動過渡） | 與 D1 同思維：一步到位，避免半套 |
| D4 | 向量 | ✅ **pgvector**（自家 PG，寫入真相） | 目標規模 150 萬向量／50 QPS 在 pgvector 甜區內，效能不輸託管；託管向量是千萬級規模的選項而非升級；避免雙系統同步複雜度（UniHR 為此需專文審計） |
| D5 | 自助註冊 | ✅ **12 個月內不開**，Sales-Led 開戶 | 防濫用洗額度 |
| D6 | enforce 溯源預設 | ⏳ 待最終確認（建議方案分級） | enforce＝「寧可保守不可編造」，不提升答題聰明度；誤殺率 1-2% |
| D7 | 雲端內部模型 | ✅ **Voyage embeddings**；稽核模型**品質優先**（建議 Terra 等級，不挑最便宜） | 稽核呼叫量 ≈ 主模型（每題一次且輸入更長），非小用量；稽核員太弱會誤殺／漏抓 |"""

assert old_table in text
text = text.replace(old_table, new_table)

# 2. Phase 1 commerce row: manual -> NewebPay directly
old_p1 = "| WS-COMMERCE | 配額強制 + 用量儀表；金流可先「合約＋手動開通」，API 預留 |"
new_p1 = "| WS-COMMERCE | 配額強制 + 用量儀表；**金流 Phase 1 直接接 NewebPay**（D3 定案，不做手動過渡） |"
assert old_p1 in text
text = text.replace(old_p1, new_p1)

# 3. CG-PAY gate moves to P1
old_gate = "| CG-PAY | 金流閉環 E2E | P2 |"
new_gate = "| CG-PAY | 金流閉環 E2E（NewebPay） | P1（D3 定案提前） |"
assert old_gate in text
text = text.replace(old_gate, new_gate)

# 4. Phase 2 commerce row adjust
old_p2 = "| WS-COMMERCE | NewebPay／Stripe 完整閉環 |"
new_p2 = "| WS-COMMERCE | NewebPay 已於 P1 上線；P2 補 Stripe（國際）或維持單軌 |"
assert old_p2 in text
text = text.replace(old_p2, new_p2)

# 5. Status: still Proposed pending D6
old_status = "**狀態**：Proposed（待決策採納後改 Accepted，並同步修訂 ADR-003）"
new_status = "**狀態**：Proposed（D1–D5、D7 已定案 2026-08-04；D6 待確認後改 Accepted，並同步修訂 ADR-003）"
assert old_status in text
text = text.replace(old_status, new_status)

path.write_text(text, encoding="utf-8")
print("decisions recorded, lines:", len(text.splitlines()))
