# Enclave 單機交付規格表

> 適用場景：第一客戶、PoC 驗收、小型組織（< 50 人）、資料完全不離境需求  
> 最後更新：2026-03-05

---

## 快速選型矩陣

| 情境 | 建議方案 | 資料是否出境 | 可服務人數 | 問答延遲 |
|---|---|---|---|---|
| 無 GPU，可連外部 API | **方案 A** | LLM 出境（其他不出） | 10–30 人 | 3–8 秒 |
| 無 GPU，完全離網 | **方案 B** | 全程不出境 | 3–8 人 | 15–40 秒 |
| GPU 8–12 GB VRAM | **方案 C** | 全程不出境 | 5–15 人 | 8–20 秒 |
| GPU 24 GB VRAM | **方案 D** | 全程不出境 | 15–30 人 | 4–10 秒 |
| GPU 48 GB VRAM | **方案 E** | 全程不出境 | 30–60 人 | 2–6 秒 |

---

## 方案 A｜無 GPU + 外部 LLM API（推薦第一客戶首選）

### 硬體需求

| 規格 | 最低 | 建議 |
|---|---|---|
| CPU | 8 核 3.0 GHz | 12 核+ |
| RAM | 32 GB DDR4 | 64 GB |
| 儲存 | 512 GB SSD | 1 TB NVMe |
| GPU | ✗ 不需要 | — |
| 網路 | 100 Mbps 固定 IP | 300 Mbps+ |
| UPS | 建議（防意外關機） | 必備 |

### 組件配置

```
LLM 推論       → Gemini API / OpenAI API（雲端）
Embedding      → Voyage AI API（雲端）
Rerank         → Voyage AI API（雲端）
向量資料庫      → PostgreSQL + pgvector（本機）
文件儲存        → 本機磁碟（UPLOAD_DIR）
任務佇列        → Redis（本機 Docker）
應用伺服器      → FastAPI（本機 Docker）
前端            → React / Nginx（本機 Docker）
```

### `.env` 關鍵設定

```env
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.0-flash-exp
VOYAGE_API_KEY=<客戶申請>
EMBEDDING_DIMENSION=1024
RETRIEVAL_RERANK=true
RETRIEVAL_USE_HYDE=true
```

### 費用估算（月）

| 項目 | 低用量（< 500 次問答） | 中用量（500–2000 次） |
|---|---|---|
| Gemini API | ~$5–15 | ~$20–60 |
| Voyage Embedding | ~$2–5 | ~$5–20 |
| **合計** | **~$7–20** | **~$25–80** |

### 優缺點

| ✅ 優點 | ⚠️ 缺點 |
|---|---|
| 問答品質最好 | LLM 內容有出境風險 |
| 不需 GPU 成本 | 依賴外部 API 可用性 |
| 部署最快（1 天內） | 長期費用隨用量增長 |
| 硬體成本最低 | 需穩定網路 |

---

## 方案 B｜無 GPU + 完全離網（CPU 推論）

### 硬體需求

| 規格 | 最低 | 建議 |
|---|---|---|
| CPU | 12 核 3.5 GHz（AVX2 支援） | 16 核+ AMD Ryzen 9 / Intel i9 |
| RAM | 64 GB DDR4 | 128 GB |
| 儲存 | 1 TB NVMe | 2 TB NVMe |
| GPU | ✗ 不需要 | — |
| 網路 | 內網即可 | — |

### 組件配置

```
LLM 推論       → Ollama（CPU 模式）：Qwen3:7b 或 Gemma3:9b
Embedding      → Ollama：bge-m3（1024-dim）
Rerank         → 停用（RETRIEVAL_RERANK=false，減少延遲）
向量資料庫      → PostgreSQL + pgvector（本機）
```

### 推薦模型（CPU 友好）

| 模型 | 大小 | RAM 需求 | CPU 速度 | 品質 |
|---|---|---|---|---|
| `qwen3:7b` | 4.7 GB | 16 GB | ~15–25 tok/s | ⭐⭐⭐ |
| `gemma3:9b` | 5.5 GB | 20 GB | ~10–18 tok/s | ⭐⭐⭐ |
| `qwen3:14b` | 9 GB | 32 GB | ~6–10 tok/s | ⭐⭐⭐⭐ |
| `llama3.2:3b` | 2 GB | 8 GB | ~30–50 tok/s | ⭐⭐ （速度快但品質低） |

### `.env` 關鍵設定

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen3:7b
EMBEDDING_PROVIDER=ollama
RETRIEVAL_RERANK=false
RETRIEVAL_USE_HYDE=false
```

### 使用體驗預期

| 操作 | 預期時間 |
|---|---|
| 簡短問答（< 200 字回答） | 15–25 秒 |
| 長文生成（會議記錄/報告） | 60–180 秒 |
| 文件向量化（每份） | 10–30 秒 |
| KB 搜尋（不含 LLM） | < 1 秒 |

### 優缺點

| ✅ 優點 | ⚠️ 缺點 |
|---|---|
| 資料完全不出境 | 回應速度慢 |
| 零 API 費用 | 高並發會卡頓 |
| 可完全離網運作 | 需要大 RAM |
| — | 生成品質低於雲端模型 |

---

## 方案 C｜GPU 8–12 GB VRAM（NVIDIA RTX 3080/4070 等級）

### 硬體需求

| 規格 | 最低 | 建議 |
|---|---|---|
| CPU | 8 核 | 12 核+ |
| RAM | 32 GB | 64 GB |
| 儲存 | 1 TB NVMe | 2 TB NVMe |
| GPU | NVIDIA RTX 3080 (10 GB) | RTX 4070 Ti (12 GB) / RTX 4080 (16 GB) |
| CUDA | 12.1+ | — |

### 推薦模型（8–12 GB VRAM）

| 模型 | VRAM 需求 | 速度 | 品質 |
|---|---|---|---|
| `qwen3:7b` (Q4) | ~5 GB | ~40–60 tok/s | ⭐⭐⭐ |
| `gemma3:9b` (Q4) | ~6 GB | ~35–50 tok/s | ⭐⭐⭐ |
| `qwen3:14b` (Q4) | ~9 GB | ~25–35 tok/s | ⭐⭐⭐⭐ |
| `bge-m3`（Embedding） | ~1.5 GB | — | ⭐⭐⭐⭐⭐（最佳） |

> ⚠️ 若同時載入 LLM + Embedding 模型，需合計 VRAM：建議 LLM 不超過 8 GB，留 2 GB 給 Embedding。

### `.env` 關鍵設定

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:14b
RETRIEVAL_RERANK=true
RERANKER_MODEL=bge-reranker-v2-m3
EMBEDDING_DIMENSION=1024
```

### 使用體驗預期

| 操作 | 預期時間 |
|---|---|
| 簡短問答 | 5–12 秒 |
| 長文生成（1000 字） | 25–60 秒 |
| 文件向量化（每份） | 2–8 秒 |

---

## 方案 D｜GPU 24 GB VRAM（RTX 4090 / RTX 3090）🌟 推薦最佳單機甜蜜點

### 硬體需求

| 規格 | 建議 |
|---|---|
| CPU | AMD Ryzen 9 7950X 或 Intel i9-14900K |
| RAM | 64 GB DDR5 |
| 儲存 | 2 TB NVMe PCIe 4.0 |
| GPU | NVIDIA RTX 4090 (24 GB) 或 RTX 3090 (24 GB) |
| CUDA | 12.4+ |
| 電源 | 1000W+ 80+ Gold |
| UPS | 必備（建議 2000VA+） |
| 散熱 | 機殼需良好通風或水冷 |

### 推薦模型（24 GB VRAM）

| 模型 | VRAM 需求 | 速度 | 品質 | 用途 |
|---|---|---|---|---|
| `qwen3:14b` (Q8) | ~15 GB | ~60–80 tok/s | ⭐⭐⭐⭐ | 主力 LLM |
| `gemma3:27b` (Q4) | ~18 GB | ~40–55 tok/s | ⭐⭐⭐⭐⭐ | 最佳品質 |
| `bge-m3` | ~1.5 GB | 高速 | ⭐⭐⭐⭐⭐ | Embedding |
| `bge-reranker-v2-m3` | ~1.5 GB | 高速 | ⭐⭐⭐⭐⭐ | Rerank |

> **推薦組合**：`gemma3:27b` (Q4, ~18 GB) + `bge-m3` (1.5 GB) + `bge-reranker` (1.5 GB) = 合計 ~21 GB，剛好裝入 24 GB。

### `.env` 關鍵設定

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=gemma3:27b
RETRIEVAL_RERANK=true
RERANKER_MODEL=bge-reranker-v2-m3
RETRIEVAL_USE_HYDE=true
EMBEDDING_DIMENSION=1024
```

### 使用體驗預期

| 操作 | 預期時間 |
|---|---|
| 簡短問答 | 3–6 秒 |
| 長文生成（1000 字） | 15–35 秒 |
| 文件向量化（每份） | 1–3 秒 |
| 批次向量化（100 份） | 5–10 分鐘 |

### 硬體估算成本（2026 年台灣市場）

| 項目 | 估算 |
|---|---|
| RTX 4090 | NT$ 50,000–65,000 |
| 主機板 + CPU + RAM | NT$ 30,000–45,000 |
| 儲存 + 電源 + 機殼 | NT$ 10,000–15,000 |
| **整機含 GPU** | **NT$ 90,000–125,000** |

---

## 方案 E｜GPU 48 GB VRAM（RTX 6000 Ada / dual GPU / A40）

### 適用場景

- 50 人以上中大型組織
- 需同時跑多個任務（多用戶並發 + 批次向量化）
- 預算充裕，追求最佳品質

### 硬體需求

| 規格 | 建議 |
|---|---|
| CPU | Xeon W 或 Threadripper |
| RAM | 128–256 GB ECC |
| 儲存 | 4 TB NVMe RAID1 |
| GPU | NVIDIA RTX 6000 Ada (48 GB) 或 2× RTX 4090 NVLink |
| 電源 | 1600W+ |

### 推薦模型

| 模型 | VRAM 需求 | 品質 |
|---|---|---|
| `qwen3:32b` (Q6) | ~26 GB | ⭐⭐⭐⭐⭐ |
| `llama4:scout` (Q4) | ~20 GB | ⭐⭐⭐⭐⭐ |
| `gemma3:27b` (Q8, 完整精度) | ~28 GB | ⭐⭐⭐⭐⭐ |

---

## 共用：OS 與基礎環境建議

| 項目 | 建議 |
|---|---|
| 作業系統 | Ubuntu 22.04 LTS Server（方案 B-E）或 Windows Server 2022（方案 A） |
| Docker | Docker Engine 26+ + Compose V2 |
| NVIDIA Driver | 535+ (CUDA 12.x) |
| 自動重啟 | `restart: always` 已設定於 docker-compose |
| 備份 | 每日 DB dump + uploads 目錄同步至外接磁碟或 NAS |
| 監控 | Prometheus + Grafana（已內建於 `monitoring/`） |
| 防火牆 | 僅開放 80/443 對內網，SSH 僅限特定 IP |

---

## 部署指令（所有方案通用）

```bash
# 1. 複製專案
git clone https://github.com/joyshotapp/Enclave.git
cd Enclave

# 2. 設定環境變數
cp .env.example .env
# 依方案填入對應設定（見上方各方案 .env 設定）

# 3. 啟動（生產模式）
docker compose -f docker-compose.prod.yml up -d

# 4. 初始化資料庫
docker compose exec web alembic upgrade head

# 5. 建立初始管理員
docker compose exec web python scripts/create_admin.py

# 6. （有 GPU 方案）預先拉取模型
ollama pull qwen3:14b
ollama pull bge-m3:latest
ollama pull bge-reranker-v2-m3:latest
```

---

## 本機部署決策樹

```
客戶資料可以出境？
├─ 可以（接受 API）
│   └─ → 方案 A（無 GPU，最快落地，品質最佳）
│
└─ 不可以（完全離網）
    │
    ├─ 預算 < NT$50,000
    │   └─ → 方案 B（CPU 推論，速度慢但可用）
    │
    ├─ 預算 NT$50,000–130,000
    │   ├─ 10 人以下  → 方案 C（GPU 12 GB）
    │   └─ 15–30 人  → 方案 D（GPU 24 GB）⭐ 推薦
    │
    └─ 預算 NT$130,000 以上
        └─ → 方案 E（GPU 48 GB）或考慮雙機架構
```

---

## 驗收測試清單（所有方案）

交付前請完成以下驗收：

- [ ] 前端登入功能正常（`http://<客戶IP>/`）
- [ ] 文件上傳並完成向量化（status = completed）
- [ ] 問答回答包含正確引用來源
- [ ] 資料夾匯入 Wizard 完整走完 5 步驟
- [ ] 生成功能：至少跑過 `meeting_minutes` 和 `draft_response`
- [ ] Word / PDF 匯出正常
- [ ] Prometheus 監控頁面可存取（`http://<客戶IP>:9090`）
- [ ] 執行測試腳本：`python scripts/run_enclave_tests.py --skip-upload`（85/85 通過）
- [ ] 備份腳本測試：`bash scripts/backup.sh` 並確認備份檔案生成

---

*文件維護：Enclave 技術團隊 | 版本：1.0.0*
