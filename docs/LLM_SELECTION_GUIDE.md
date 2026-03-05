# Enclave LLM 選型指南

> 根據程式碼中 5 個 LLM 呼叫點整理（4 個功能 × 獨立設定）  
> 最後更新：2026-03-05

---

## 系統 LLM 架構（5 個呼叫點 → 4 個 .env 槽位）

```
使用者操作                 LLM 呼叫點                .env 槽位
──────────────────────────────────────────────────────────────────
① 問答（RAG Q&A）      →  主力 LLM                  LLM_PROVIDER
                                                       OLLAMA_MODEL / GEMINI_MODEL / OPENAI_MODEL

② 生成（內容生成）      →  主力 LLM（同上共用）       LLM_PROVIDER（與問答共用）

③ 問答流程內部            查詢改寫 / contextualize    INTERNAL_LLM_PROVIDER
   （使用者不直接感知）  →  / 對話分類                  INTERNAL_OLLAMA_MODEL
                           （省 API 費的輕量任務）

④ 掃資料夾生摘要        →  專用 Ollama（固定本地）    OLLAMA_SCAN_URL
   （Wizard AI 摘要）                                  OLLAMA_SCAN_MODEL

⑤ 向量化（文件/問題）   →  Embedding 模型            EMBEDDING_PROVIDER
                                                       VOYAGE_MODEL / OLLAMA_EMBED_MODEL
──────────────────────────────────────────────────────────────────
```

> **注意**：①問答 和 ②生成 共用同一個 `LLM_PROVIDER` 槽位。  
> **注意**：④掃資料夾摘要 固定走 Ollama（`OLLAMA_SCAN_MODEL`），不支援雲端 API。  
> **注意**：③查詢改寫 是問答流程的內部步驟，可獨立設定較輕量的本地模型來省 API 費。

---

## 一、雲端 LLM 選項（無 GPU，需要 API Key）

### OpenAI（LLM_PROVIDER=openai）

| 模型 | OPENAI_MODEL 值 | 品質 | 速度 | 費用（每 1M tokens） | 中文能力 | 推薦場景 |
|---|---|---|---|---|---|---|
| **GPT-4.1** | `gpt-4.1` | ⭐⭐⭐⭐⭐ | 快 | I: $2 / O: $8 | ⭐⭐⭐⭐ | 最高品質需求 |
| **GPT-4.1 mini** | `gpt-4.1-mini` | ⭐⭐⭐⭐ | 極快 | I: $0.40 / O: $1.60 | ⭐⭐⭐⭐ | 🌟 CP 值最高 |
| **GPT-4o** | `gpt-4o` | ⭐⭐⭐⭐⭐ | 快 | I: $2.50 / O: $10 | ⭐⭐⭐⭐ | 複雜法律/財務分析 |
| **GPT-4o mini** | `gpt-4o-mini` | ⭐⭐⭐ | 極快 | I: $0.15 / O: $0.60 | ⭐⭐⭐ | 目前預設，預算有限 |
| o3-mini | `o3-mini` | ⭐⭐⭐⭐⭐ | 慢 | I: $1.10 / O: $4.40 | ⭐⭐⭐ | 深度推理（不適合即時問答） |

> **現狀**：`.env` 設定 `OPENAI_MODEL=gpt-4o-mini`（費用最低但品質中等）  
> **建議升級**：改為 `gpt-4.1-mini`，品質提升明顯，費用只增加約 2.5x

### Google Gemini（LLM_PROVIDER=gemini）

| 模型 | GEMINI_MODEL 值 | 品質 | 速度 | 費用（每 1M tokens） | 中文能力 | 推薦場景 |
|---|---|---|---|---|---|---|
| **Gemini 2.5 Pro** | `gemini-2.5-pro` | ⭐⭐⭐⭐⭐ | 中 | I: $1.25 / O: $10 | ⭐⭐⭐⭐⭐ | 最佳中文品質 |
| **Gemini 2.0 Flash** | `gemini-2.0-flash` | ⭐⭐⭐⭐ | 極快 | I: $0.10 / O: $0.40 | ⭐⭐⭐⭐⭐ | 🌟 日常首選 |
| **Gemini 2.5 Flash** | `gemini-2.5-flash-preview-04-17` | ⭐⭐⭐⭐⭐ | 快 | I: $0.15 / O: $0.60 | ⭐⭐⭐⭐⭐ | 品質與速度平衡 |
| Gemini 2.0 Flash Lite | `gemini-2.0-flash-lite` | ⭐⭐⭐ | 極快 | I: $0.075 / O: $0.30 | ⭐⭐⭐⭐ | 最便宜 |
| Gemini 3 Flash (現用) | `gemini-3-flash-preview` | ⭐⭐⭐⭐ | 極快 | I: $0.10 / O: $0.40 | ⭐⭐⭐⭐⭐ | 目前預設 |

> **現狀**：`.env` 設定 `LLM_PROVIDER=gemini`，`GEMINI_MODEL=gemini-3-flash-preview`  
> **建議**：升級至 `gemini-2.5-flash-preview-04-17`，中文品質更穩定

### 雲端方案優缺點總覽

| 項目 | OpenAI | Gemini |
|---|---|---|
| 中文品質 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 回應速度 | 快 | 極快 |
| 免費額度 | 無 | 有（Gemini API 免費層） |
| 資料隱私 | 資料傳至美國 | 資料傳至美國/台灣節點 |
| 穩定性 | 業界最穩定 | 偶有預覽版不穩定 |
| 繁體中文 | 自然但偶有簡體混入 | 繁體中文非常自然 |

---

## 二、本地 Ollama LLM 選項（有 GPU 或高 RAM）

### 設定方式

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=<下表模型名稱>
```

### 輕量模型（CPU 可跑 / 低 VRAM）

| 模型 | OLLAMA_MODEL 值 | VRAM/RAM | 速度 | 品質 | 中文 | 適用場景 |
|---|---|---|---|---|---|---|
| Llama 3.2 3B | `llama3.2:3b` | ~4 GB RAM | 極快 | ⭐⭐ | ⭐⭐ | 測試/Dev only，不建議生產 |
| Qwen3 1.7B | `qwen3:1.7b` | ~3 GB RAM | 極快 | ⭐⭐ | ⭐⭐⭐ | CPU 可跑，中文尚可 |
| **Qwen3 7B** | `qwen3:7b` | ~5 GB VRAM (CPU: 16 GB RAM) | 快 | ⭐⭐⭐ | ⭐⭐⭐⭐ | CPU 推論最佳選擇 |
| Gemma3 9B | `gemma3:9b` | ~6 GB VRAM (CPU: 20 GB RAM) | 中 | ⭐⭐⭐ | ⭐⭐⭐ | CPU 可用，英文較強 |

### 中階模型（需要 GPU 8–16 GB VRAM）

| 模型 | OLLAMA_MODEL 值 | VRAM 需求 | 速度 | 品質 | 中文 | 適用場景 |
|---|---|---|---|---|---|---|
| **Qwen3 14B** | `qwen3:14b` | ~9 GB (Q4) | 中快 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 🌟 12 GB GPU 最佳選擇 |
| Llama4 Scout | `llama4:scout` | ~9 GB (Q4) | 快 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 英文強，MoE 架構 |
| Mistral Small 3 | `mistral-small3.1:24b` | ~15 GB | 中 | ⭐⭐⭐⭐ | ⭐⭐⭐ | 多語言，含視覺 |

### 高階模型（需要 GPU 24 GB VRAM）

| 模型 | OLLAMA_MODEL 值 | VRAM 需求 | 速度 | 品質 | 中文 | 適用場景 |
|---|---|---|---|---|---|---|
| **Qwen3 14B Q8** | `qwen3:14b-q8_0` | ~15 GB | 快 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 24 GB GPU 高品質選擇 |
| **Gemma3 27B** | `gemma3:27b` | ~18 GB (Q4) | 中 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 🌟 目前系統 Scan 使用，品質最佳 |
| Qwen3 32B | `qwen3:32b` | ~21 GB (Q4) | 中慢 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 24 GB 極限，最強中文 |
| Llama4 Maverick | `llama4:maverick` | ~24 GB | 中 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Meta 最新旗艦 |

### 超大模型（需要 GPU 48 GB+ VRAM）

| 模型 | OLLAMA_MODEL 值 | VRAM 需求 | 品質 | 中文 |
|---|---|---|---|---|
| Qwen3 32B Q8 | `qwen3:32b-q8_0` | ~34 GB | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Gemma3 27B Q8 | `gemma3:27b-q8_0` | ~28 GB | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| DeepSeek R1 32B | `deepseek-r1:32b` | ~22 GB | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 

---

## 三、Embedding 模型選項

> 設定：`EMBEDDING_PROVIDER=voyage` 或 `EMBEDDING_PROVIDER=ollama`

| 模型 | 提供商 | 設定 | 向量維度 | 中文品質 | 費用 |
|---|---|---|---|---|---|
| **voyage-4-lite** | Voyage AI（雲端） | `VOYAGE_MODEL=voyage-4-lite` | 1024 | ⭐⭐⭐⭐⭐ | $0.02/M tokens |
| voyage-4 | Voyage AI（雲端） | `VOYAGE_MODEL=voyage-4` | 2048 | ⭐⭐⭐⭐⭐ | $0.06/M tokens |
| **bge-m3** | Ollama（本地） | `OLLAMA_EMBED_MODEL=bge-m3` | 1024 | ⭐⭐⭐⭐⭐ | 免費 |
| nomic-embed-text | Ollama（本地） | `OLLAMA_EMBED_MODEL=nomic-embed-text` | 768 | ⭐⭐⭐ | 免費 |

> `bge-m3` 是本地 Embedding 的最佳選擇，中文效果與 voyage-4-lite 幾乎相當。  
> VRAM 需求：~1.5 GB（可與 LLM 共存於 24 GB GPU）

---

## 四、建議組合方案

### 方案 A：雲端全託管（無 GPU，最快落地）

```env
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.5-flash-preview-04-17

INTERNAL_LLM_PROVIDER=gemini
# 內部分類任務也用 Gemini（便宜，gemini-2.0-flash）

EMBEDDING_PROVIDER=voyage
VOYAGE_MODEL=voyage-4-lite
RETRIEVAL_RERANK=true

LLAMAPARSE_ENABLED=true   # 高品質 PDF 解析
```

| 指標 | 預估 |
|---|---|
| 問答延遲 | 3–6 秒 |
| 月費（1000 次問答） | ~$5–20 |
| 資料出境 | LLM + Embedding 全出境 |

---

### 方案 B：雲端 LLM + 本地 Embedding（資料半保護）

> 向量不出境，LLM prompt 仍出境

```env
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.5-flash-preview-04-17

INTERNAL_LLM_PROVIDER=ollama
INTERNAL_OLLAMA_MODEL=qwen3:7b    # 內部任務走本地，省 API 費

EMBEDDING_PROVIDER=ollama
OLLAMA_EMBED_MODEL=bge-m3
RETRIEVAL_RERANK=false            # 無 Voyage 不能 rerank

LLAMAPARSE_ENABLED=false
```

| 指標 | 預估 |
|---|---|
| 問答延遲 | 4–8 秒 |
| 月費（1000 次問答） | ~$2–8 |
| 資料出境 | 僅 LLM 查詢出境 |

---

### 方案 C：本地 GPU 12 GB（中度隱私）

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:14b

INTERNAL_LLM_PROVIDER=ollama
INTERNAL_OLLAMA_MODEL=qwen3:7b    # 輕量任務用小模型

EMBEDDING_PROVIDER=ollama
OLLAMA_EMBED_MODEL=bge-m3
RETRIEVAL_RERANK=false

OLLAMA_SCAN_MODEL=qwen3:14b
LLAMAPARSE_ENABLED=false
```

| 指標 | 預估 |
|---|---|
| 問答延遲 | 8–18 秒 |
| 月費 | $0（零 API 費） |
| 資料出境 | 完全不出境 |
| GPU 建議 | RTX 4070 Ti / RTX 4080 |

---

### 方案 D：本地 GPU 24 GB（推薦最佳單機）🌟

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:32b            # 或 gemma3:27b

INTERNAL_LLM_PROVIDER=ollama
INTERNAL_OLLAMA_MODEL=qwen3:7b

EMBEDDING_PROVIDER=ollama
OLLAMA_EMBED_MODEL=bge-m3
RETRIEVAL_RERANK=false

OLLAMA_SCAN_MODEL=gemma3:27b
LLAMAPARSE_ENABLED=false
```

| 指標 | 預估 |
|---|---|
| 問答延遲 | 4–10 秒 |
| 月費 | $0（零 API 費） |
| 資料出境 | 完全不出境 |
| GPU 建議 | RTX 4090 / RTX 3090 |

---

### 方案 E：混合最優（GPU + 雲端 Rerank）

> 本地 LLM 保護主要資料，Voyage Rerank 提升檢索品質

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:32b

INTERNAL_LLM_PROVIDER=ollama
INTERNAL_OLLAMA_MODEL=qwen3:7b

EMBEDDING_PROVIDER=voyage          # Voyage embedding 品質略高
VOYAGE_MODEL=voyage-4-lite
RETRIEVAL_RERANK=true              # Voyage rerank，大幅提升精準度
```

| 指標 | 預估 |
|---|---|
| 問答延遲 | 5–12 秒（含 rerank） |
| 月費 | ~$2–5（僅 Voyage 費用） |
| 資料出境 | 僅文件 chunk 送至 Voyage 做向量化 |

---

## 五、快速決策表

```
有沒有 GPU？
│
├── 沒有
│   ├── 資料可以出境？ Yes → 方案 A（Gemini 2.5 Flash + Voyage）⭐ 推薦
│   └── 資料不能出境？     → 方案 B partial（Gemini 2.5 Flash + 本地 bge-m3）
│                          （注意：LLM 查詢仍出境）
│
└── 有 GPU
    ├── 12 GB VRAM
    │   └── → 方案 C（qwen3:14b）
    ├── 24 GB VRAM
    │   ├── 完全離網 → 方案 D（qwen3:32b 或 gemma3:27b）⭐ 推薦
    │   └── 可用 Voyage → 方案 E（qwen3:32b + Voyage Rerank）
    └── 48 GB VRAM
        └── → 方案 D 使用 qwen3:32b Q8 或 llama4:maverick
```

---

## 六、Ollama 安裝指令

```bash
# 方案 B / C 內部任務
ollama pull qwen3:7b

# 方案 C 主力 LLM
ollama pull qwen3:14b

# 方案 D 主力 LLM（擇一）
ollama pull qwen3:32b       # 中文最強
ollama pull gemma3:27b      # 現系統預設 Scan 模型，品質也很好

# 共用 Embedding（所有本地方案）
ollama pull bge-m3

# 確認已安裝
ollama list
```

---

## 七、環境變數對照表（完整）

| .env 變數 | 說明 | 可選值 |
|---|---|---|
| `LLM_PROVIDER` | 主力 LLM 提供商 | `openai` / `gemini` / `ollama` |
| `OPENAI_MODEL` | OpenAI 模型名稱 | `gpt-4.1-mini` / `gpt-4o` / `gpt-4o-mini` |
| `GEMINI_MODEL` | Gemini 模型名稱 | `gemini-2.5-flash-preview-04-17` / `gemini-2.0-flash` / `gemini-2.5-pro` |
| `OLLAMA_MODEL` | 主力 Ollama 模型 | `qwen3:14b` / `qwen3:32b` / `gemma3:27b` |
| `OLLAMA_BASE_URL` | Ollama 服務 URL | `http://host.docker.internal:11434` |
| `INTERNAL_LLM_PROVIDER` | 內部任務 LLM | `ollama` / `gemini` / `openai` |
| `INTERNAL_OLLAMA_MODEL` | 內部任務 Ollama 模型 | `qwen3:7b` / `gemma3:9b` |
| `EMBEDDING_PROVIDER` | 向量化提供商 | `voyage` / `ollama` |
| `VOYAGE_MODEL` | Voyage 模型 | `voyage-4-lite` / `voyage-4` |
| `OLLAMA_EMBED_MODEL` | 本地 Embedding 模型 | `bge-m3` |
| `EMBEDDING_DIMENSION` | 向量維度（需與模型匹配） | `1024` (bge-m3 / voyage-4-lite) / `2048` (voyage-4) |
| `RETRIEVAL_RERANK` | 啟用重排序 | `true` / `false` |
| `OLLAMA_SCAN_MODEL` | 資料夾掃描 AI 摘要模型 | `gemma3:27b` / `qwen3:14b` |
| `LLAMAPARSE_ENABLED` | 高品質 PDF 解析 | `true` / `false` |

---

*文件維護：Enclave 技術團隊 | v1.0.0*
