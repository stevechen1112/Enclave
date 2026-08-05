"""Append cloud resource inventory appendix to CLOUD_AND_COMMERCIALIZATION_PLAN.md."""
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "docs" / "CLOUD_AND_COMMERCIALIZATION_PLAN.md"
text = path.read_text(encoding="utf-8")

appendix = """
---

## 15. 附錄：雲端資源／服務總表（2026-08-04）

> 本表彙整計畫採用的所有外部雲端資源。形態欄：A＝地端自管、B＝託管私有雲、C＝多租戶 SaaS。
> 原則：**雲端形態零 GPU**；每項皆標註地端替代（形態 A 不使用任何外部雲端資源）。

### 15.1 邊緣與網路

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **Cloudflare**（或同等） | CDN、WAF、DDoS 防護、TLS 終止 | B、C | P1 | 免費～Pro 級即夠初期 |

### 15.2 計算與部署

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **Linode VM／VPC**（或 AWS／GCP 同等） | Compose 部署 API／worker／DB | B、C | P1–P2 | 延續 UniHR 營運經驗（D2） |
| **託管 PostgreSQL**（選配） | 取代自管 PG | C | P2–P3 | 含自動備份／failover |
| **PgBouncer** | DB 連線池（自架、非雲服務） | C | P2 | CG-CAPACITY 前置 |
| **K8s（EKS／GKE／AKS 或 k3s）** | 僅規模證明需要時評估 | C | P3 | 明確不在 P1–P2 |

### 15.3 儲存

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **Cloudflare R2**（首選）或 Linode Object Storage／AWS S3 | 文件物件儲存（S3 API） | B、C | P1 | key 前綴隔離租戶；地端用 MinIO／本地 |
| **pgvector**（自管 PG 內） | 向量索引＝寫入真相 | A、B、C | 既有 | 預設不外包 |
| **Pinecone／Qdrant Cloud**（選配） | 託管向量（大規模時） | C | P2+ | D4；PG 永遠是真相來源 |

### 15.4 AI 模型服務

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **OpenAI gpt-5.6-luna** | 主問答 LLM | A、B、C | 既有 | 盲測對決定案；Sol 退場 |
| **OpenAI gpt-5.6-terra** | 備用／升級（enforce 重生成、高難意圖） | A、B、C | 既有 | 僅升級路徑呼叫 |
| **Voyage AI rerank-2.5** | 檢索重排序 | A、B、C | 既有 | API key 已驗證 |
| **Voyage AI embeddings** | 雲端形態 embedding | B、C | P1（D7） | 地端維持本地 bge-m3 |
| **Mistral OCR API** | 掃描件 OCR（雲端形態預設） | B、C | P1 | 實測 30.3% 優於地端 DeepDoc；4 美元/千頁 |
| **Gemini／OpenAI 雲端 OCR** | OCR 替代供應商 | B、C | 選配 | `cloud_ocr.py` 已抽象 |
| **廉價雲端小模型**（稽核用） | 逐字溯源稽核（SaaS） | B、C | P1（D7） | 地端維持本地 qwen3.6:35b |

### 15.5 金流與商業

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **NewebPay 藍新金流** | 台灣市場收款 | B、C | P2 | 對齊 UniHR 已上線路徑 |
| **Stripe**（完整實作或不做） | 國際市場收款 | C | P2+ | 禁止半套（UniHR 教訓） |

### 15.6 身分與通訊

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **Google／Microsoft OAuth** | 企業 SSO | B、C | P1 | 掛載既有 skeleton |
| **SMTP／Resend／AWS SES** | 交易郵件（驗證／邀請／重設） | B、C | P1 | 擇一 |

### 15.7 觀測與安全

| 服務 | 用途 | 形態 | 階段 | 備註 |
|------|------|------|------|------|
| **Sentry** | 錯誤追蹤（web＋worker） | B、C | P1 | |
| **Langfuse**（雲端或自架） | LLM／RAG trace，串 source_verification | B、C | P1 | 自架則無外部依賴 |
| **Prometheus＋Grafana**（自架） | 指標與儀表 | A、B、C | 既有 | 非外部雲服務 |
| **ClamAV**（自架容器） | 上傳掃毒 fail-closed | B、C | P1 | 非外部雲服務 |
| **KMS／Vault** | Secrets 管理 | B、C | P1–P2 | 淘汰純本地 Fernet key 檔 |

### 15.8 自架 sidecar（非外部雲服務，列此供完整對照）

| 元件 | 雲端形態部署方式 |
|------|------------------|
| RAGFlow | **純 CPU 容器池**（掃描件路由 Mistral OCR API） |
| PipesHub | B：每客專屬；C：binding 映射 |
| WeKnora | 同上 |
| Redis | 自管或託管（cache＋Celery queue） |

### 15.9 成本量級速查（形態 C、100 租戶基準）

| 項目 | 量級估算 | 依據 |
|------|----------|------|
| Mistral OCR（開戶全量 100 萬頁） | 約 4,000 美元一次性 | 4 美元/千頁 |
| LLM（Luna，日均 20 萬次查詢） | 依 Luna 單價計；較 Sol 省一個量級 | 消融對決後定案 |
| R2 儲存（250 GB） | 每月數美元級 | R2 無 egress 費 |
| VM／託管 PG | 每月數百美元級（P1–P2 Compose 規模） | Linode 級定價 |

> 原則：品質路徑成本進 COGS 由方案矩陣吸收（§3.4）；每千次查詢 COGS 上限為方案設計必要輸入。
"""

anchor = "**本文件是路線圖，不是已完成聲明。** 採納前請完成 §9 決策；採納後以 §11 閘門為唯一進度語言。"
assert anchor in text
text = text.replace(anchor, anchor + "\n" + appendix)
path.write_text(text, encoding="utf-8")
print("appendix added, lines:", len(text.splitlines()))
