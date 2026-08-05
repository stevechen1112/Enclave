"""CLOUD_AND_COMMERCIALIZATION_PLAN.md 完整檢視後的修正（2026-08-04）。

修正項：
1. Sol 過時引用 ×3（§1.1 現況表、§4.4 容量表、R2 風險）→ Luna
2. 腐壞路徑「<TAB>ests/load/」×2 → `tests/load/`
3. 腐壞金額「\\/千頁」「約 \\」×1 處 → $4/千頁、$4K
4. 簡體「廉价」→「廉價」
5. 「與fleet」→「與 fleet」
6. 真缺口：內部模型（稽核／embedding／scan）在零 GPU 雲端的落點 → §4.4 加列 + WS-CAPACITY 加項 + D7 決策點
"""
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "docs" / "CLOUD_AND_COMMERCIALIZATION_PLAN.md"
text = path.read_text(encoding="utf-8")
fixes = []

def rep(old, new, label):
    global text
    assert old in text, f"NOT FOUND: {label}"
    text = text.replace(old, new)
    fixes.append(label)

# 1a. §1.1 現況表：Sol → Luna
rep(
    "| 主 LLM / Rerank / 雲端 OCR | **已在雲端 API**（Sol／Voyage／選配 OCR） | `deployment_mode.py`；`cloud_ocr.py` |",
    "| 主 LLM / Rerank / 雲端 OCR | **已在雲端 API**（Luna／Voyage／選配 OCR；Sol 已退場、Terra 備用） | `deployment_mode.py`；`cloud_ocr.py` |",
    "1a §1.1 Sol→Luna",
)

# 1b. §4.4 容量表：LLM API（Sol）→（Luna）
rep(
    "| LLM API（Sol） | ⚠️ 需管理 |",
    "| LLM API（Luna） | ⚠️ 需管理 |",
    "1b §4.4 Sol→Luna",
)

# 1c. R2 風險：Sol → Luna
rep(
    "| R2 | 上雲後 COGS 失控（Sol＋OCR＋rerank） | 高 |",
    "| R2 | 上雲後 COGS 失控（LLM＋OCR＋rerank） | 高 |",
    "1c R2 Sol→generic",
)

# 2. 腐壞路徑（tab 吃掉了反斜線與 t）
rep(
    "既有 Locust/k6 基準（\tests/load/）需擴到 1,000 VU",
    "既有 Locust/k6 基準（`tests/load/`）需擴到 1,000 VU",
    "2a tests/load 路徑（§4.4）",
)
rep(
    "擴充 \tests/load/：1,000 VU",
    "擴充 `tests/load/`：1,000 VU",
    "2b tests/load 路徑（§5.11）",
)

# 3. 腐壞金額（PowerShell 把 $4 當變數吃掉）
rep(
    "已實測 30.3% 優於 DeepDoc 24.2%、\\/千頁，100 萬頁全量約 \\；觸發邏輯",
    "已實測 30.3% 優於 DeepDoc 24.2%、4 美元/千頁，100 萬頁全量約 4,000 美元；觸發邏輯",
    "3 OCR 金額",
)

# 4. 簡體字
rep("本地／廉价內部模型", "本地／廉價內部模型", "4 廉价→廉價")

# 5. 缺空格
rep("與fleet 監控", "與 fleet 監控", "5 fleet 空格")

# 6. 真缺口：內部模型雲端落點
rep(
    "| 稽核層（source_verifier） | ✅ 可承載 | shadow 走內部小模型；SaaS 可改廉價雲端小模型，不佔主模型額度 |",
    "| 稽核層（source_verifier） | ⚠️ 需落點決策 | 現跑本地 Ollama qwen3.6:35b（23GB）；零 GPU 雲端 CPU 跑不動 → SaaS 改廉價雲端小模型（見 D7） |\n"
    "| Embedding（bge-m3） | ⚠️ 需落點決策 | 現跑本地 Ollama；雲端零 GPU 下 CPU embedding 慢 → 建議 Voyage API（已有 key、UniHR 實戰使用中）或 CPU 小實例池（見 D7） |",
    "6a §4.4 內部模型落點",
)
rep(
    "| 容量儀表 | Grafana：每租戶 QPS／入庫延遲／LLM 錯誤率／DB 連線使用率 |",
    "| 容量儀表 | Grafana：每租戶 QPS／入庫延遲／LLM 錯誤率／DB 連線使用率 |\n"
    "| 內部模型落點 | 稽核／embedding／scan 三角色在雲端的 provider 切換（`deployment_mode.py` 已抽象，僅需設定與回歸驗證） |",
    "6b §5.11 內部模型落點",
)
rep(
    "| D6 | enforce 溯源預設 | 全開 / 方案分級 | **方案分級**（Team shadow / Business+ enforce） |",
    "| D6 | enforce 溯源預設 | 全開 / 方案分級 | **方案分級**（Team shadow / Business+ enforce） |\n"
    "| D7 | 雲端內部模型落點 | Voyage embed＋雲端小模型稽核 / CPU 自跑小模型池 | **雲端 API 優先**（零 GPU 原則一致；地端維持 Ollama） |",
    "6c D7 決策點",
)

path.write_text(text, encoding="utf-8")
print("fixes applied:", len(fixes))
for f in fixes:
    print(" -", f)
print("U+FFFD:", text.count("\ufffd"))
