# OpenClaw → UniHR 升級參考手冊

> **來源分析日期**：2026-02-19  
> **參考專案**：OpenClaw（`C:\Users\User\Desktop\openclaw`）  
> **設計文件**：`C:\Users\User\Desktop\openclaw\notes\openclaw-design-reference.md`  
> **目的**：將 OpenClaw 值得借鑑的工程實作，轉化為 UniHR SaaS 可直接落地的升級方案。

---

## TL;DR — 最高價值的 3 個改造

| 排名 | 改造項目 | 解決的現有痛點 | 預估工時 |
|------|----------|--------------|---------|
| 🥇 | **LLM Failover + Cooldown** | Core API rate limit → P95 延遲 77s；文件處理 failed | 1 天 |
| 🥈 | **SSE 事件流 runId/seq 保序** | 前端重連漏事件；串流一致性 | 0.5 天 |
| 🥉 | **Embedding Cache + 批次重試** | Voyage 費用 15-30%；文件 failed 率 | 1 天 |

---

## 目錄

1. [P0：LLM Failover + Auth Profile Cooldown](#p0-llm-failover--auth-profile-cooldown)
2. [P0：SSE 事件流 runId/seq 保序機制](#p0-sse-事件流-runidseq-保序機制)
3. [P1：Embedding Query Cache](#p1-embedding-query-cache)
4. [P1：Hybrid Search 可調權重（替換純 RRF）](#p1-hybrid-search-可調權重替換純-rrf)
5. [P1：文件 Embedding 批次重試（指數退避）](#p1-文件-embedding-批次重試指數退避)
6. [P2：Feature Flag 記憶體快取](#p2-feature-flag-記憶體快取)
7. [P2：Subsystem Logger 分類日誌](#p2-subsystem-logger-分類日誌)
8. [P2：RBAC Method Matrix 集中化](#p2-rbac-method-matrix-集中化)
9. [P2：路徑安全驗證（Path Traversal 防護）](#p2-路徑安全驗證path-traversal-防護)
10. [不適合轉用的部分](#不適合轉用的部分)
11. [升級優先排序總表](#升級優先排序總表)

---

## P0：LLM Failover + Auth Profile Cooldown

### 問題根因

docs/reports/QUALITY_PERFORMANCE_REPORT.md 記錄：
- 平均回應 **48.9 秒**，P95 = **77.3 秒**
- 主瓶頸：Core API（外部 UniHR Core，GPT-4o）15-30 秒
- 5 個 worker 並發即觸發 rate limit，導致比首次測試慢 75%
- `OpenAI gpt-4o-mini` 只有單一 API key，限流時整個聊天功能掛掉
- Voyage embedding 無重試，`process_document_task` 失敗 = 文件永久 `status=failed`

### OpenClaw 解法

**參考檔案**：
- `C:\Users\User\Desktop\openclaw\src\agents\model-fallback.ts`
- `C:\Users\User\Desktop\openclaw\src\agents\auth-profiles\usage.ts`

**核心設計**：
```
primary provider → fallback chain → 每個 provider 有獨立 cooldown
失敗分類：rate_limit / auth / transient / permanent → 各自退避策略
指數退避公式：min(1h, 5min × 5^(errorCount-1))
errorCount=1 → 5min, 2 → 25min, 3 → 125min (capped 60min)
Profile 在 cooldown 期間直接跳過，不浪費任何一次 API 呼叫
```

### UniHR 轉用方案

**新增檔案**：`app/services/llm_failover.py`

```python
# app/services/llm_failover.py
"""
LLM Failover Service — 仿 OpenClaw model-fallback.ts 設計
支援：
  - 多 key/provider 輪換
  - 失敗分類（rate_limit / auth / transient / permanent）
  - 指數退避 cooldown
  - profile 狀態持久化（Redis）
"""
import asyncio
import time
import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Any, Optional
from enum import Enum

import openai
import redis as redis_lib

from app.config import settings

logger = logging.getLogger(__name__)


class FailoverReason(str, Enum):
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    TRANSIENT = "transient"
    PERMANENT = "permanent"


@dataclass
class LLMProfile:
    name: str
    api_key: str
    model: str
    provider: str = "openai"
    base_url: Optional[str] = None
    # runtime state（可存 Redis）
    cooldown_until: float = 0.0
    error_count: int = 0
    last_used: float = 0.0

    def is_in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def calculate_cooldown_ms(self) -> int:
        """指數退避：min(1h, 5min × 5^(errorCount-1))"""
        normalized = max(1, self.error_count)
        return min(
            60 * 60 * 1000,                          # 1 小時上限
            60 * 1000 * (5 ** min(normalized - 1, 3)) # 5min / 25min / 125min → capped
        )

    def mark_failure(self, reason: FailoverReason):
        self.error_count += 1
        cooldown_ms = self.calculate_cooldown_ms()
        self.cooldown_until = time.time() + cooldown_ms / 1000
        logger.warning(
            f"[LLM Failover] profile={self.name} reason={reason.value} "
            f"error_count={self.error_count} cooldown={cooldown_ms/1000:.0f}s"
        )

    def mark_success(self):
        self.error_count = 0
        self.cooldown_until = 0.0
        self.last_used = time.time()


def _classify_openai_error(err: Exception) -> FailoverReason:
    """將 OpenAI exception 分類，對應 OpenClaw 的 coerceToFailoverError"""
    if isinstance(err, openai.RateLimitError):
        return FailoverReason.RATE_LIMIT
    if isinstance(err, openai.AuthenticationError):
        return FailoverReason.AUTH
    if isinstance(err, (openai.APITimeoutError, openai.APIConnectionError)):
        return FailoverReason.TRANSIENT
    if isinstance(err, openai.APIStatusError):
        if err.status_code in (500, 502, 503, 504):
            return FailoverReason.TRANSIENT
        return FailoverReason.PERMANENT
    return FailoverReason.TRANSIENT


async def run_with_llm_fallback(
    profiles: list[LLMProfile],
    run_fn: Callable[[LLMProfile], Any],
    on_error: Optional[Callable] = None,
) -> Any:
    """
    依序嘗試每個 profile，跳過 cooldown 中的 profile。
    對應 OpenClaw runWithModelFallback。
    """
    last_error: Optional[Exception] = None

    for i, profile in enumerate(profiles):
        if profile.is_in_cooldown():
            logger.debug(
                f"[LLM Failover] skipping profile={profile.name} (in cooldown until "
                f"{time.strftime('%H:%M:%S', time.localtime(profile.cooldown_until))})"
            )
            continue

        try:
            result = await run_fn(profile)
            profile.mark_success()
            if i > 0:
                logger.info(f"[LLM Failover] succeeded on fallback profile={profile.name}")
            return result

        except asyncio.CancelledError:
            # 使用者中斷，直接 rethrow
            raise

        except Exception as err:
            reason = _classify_openai_error(err)
            profile.mark_failure(reason)
            last_error = err

            if on_error:
                on_error({"profile": profile.name, "error": str(err),
                          "reason": reason.value, "attempt": i + 1, "total": len(profiles)})

            if reason == FailoverReason.PERMANENT:
                # 不可恢復錯誤（如 invalid_request_error），不繼續嘗試
                raise

    raise RuntimeError(
        f"All LLM profiles exhausted or in cooldown. Last error: {last_error}"
    ) from last_error


# ── 預設 profile 建立（從 settings 讀取）──

def build_default_openai_profiles() -> list[LLMProfile]:
    """
    從 settings 建立 profile list。
    若要多 key，可在 .env 追加：
      OPENAI_API_KEY_2=sk-...
      OPENAI_API_KEY_3=sk-...
    """
    profiles = []
    primary_key = getattr(settings, "OPENAI_API_KEY", "")
    if primary_key:
        profiles.append(LLMProfile(
            name="openai-primary",
            api_key=primary_key,
            model=settings.OPENAI_MODEL,
        ))

    # 支援備用 key（可選）
    for i in range(2, 6):
        key = getattr(settings, f"OPENAI_API_KEY_{i}", "")
        if key:
            profiles.append(LLMProfile(
                name=f"openai-key-{i}",
                api_key=key,
                model=settings.OPENAI_MODEL,
            ))

    return profiles


# ── 使用範例（在 ChatOrchestrator 中整合）──
#
# profiles = build_default_openai_profiles()
#
# async def run_generation(profile: LLMProfile):
#     client = openai.AsyncOpenAI(api_key=profile.api_key)
#     response = await client.chat.completions.create(...)
#     return response
#
# result = await run_with_llm_fallback(profiles, run_generation)
```

**整合到 `app/services/chat_orchestrator.py`**：
- 將 `self._openai_async.chat.completions.create(...)` 包進 `run_with_llm_fallback()`
- `ChatOrchestrator.__init__` 改為 `self._profiles = build_default_openai_profiles()`

**整合到 `app/services/core_client.py`**：
- 對 Core API 的 HTTP 呼叫加相同的 failover + 指數退避（不同是用 httpx 而非 openai SDK）

**`app/config.py` 新增 optional 備用 key**：
```python
OPENAI_API_KEY_2: str = ""
OPENAI_API_KEY_3: str = ""
```

---

## P0：SSE 事件流 runId/seq 保序機制

### 問題根因

[app/api/v1/endpoints/chat.py](../app/api/v1/endpoints/chat.py) 的 SSE 直接 push JSON，無 `seq`、無 `stream` 分類。前端：
- 網路抖動導致重連後，無法判斷是否漏掉事件
- 多個並行串流無法區分事件歸屬
- 無法在 Grafana 按事件流類型統計（status / token / error 各佔多少）

### OpenClaw 解法

**參考檔案**：`C:\Users\User\Desktop\openclaw\src\infra\agent-events.ts`

```typescript
// 每個 runId 獨立維護單調遞增 seq
const seqByRun = new Map<string, number>();
type AgentEventPayload = {
  runId: string;  // 全域唯一，關聯一次完整問答
  seq: number;    // 每個 runId 內單調遞增，供客戶端偵測漏包
  stream: "lifecycle" | "tool" | "assistant" | "error"; // 事件分流
  ts: number;     // Unix ms timestamp
  sessionKey: string; // 多租戶關聯
  data: Record<string, unknown>;
};
```

前端收到 `seq` 跳號（如 3 → 5）即知漏包，可觸發 reconnect。

### UniHR 轉用方案

**新增檔案**：`app/services/event_stream.py`

```python
# app/services/event_stream.py
"""
SSE 事件流工具 — 仿 OpenClaw agent-events.ts 設計
提供：
  - runId 綁定的 seq 保序
  - 事件分流（lifecycle / retrieval / assistant / error）
  - 統一的 SSE 封包格式
"""
import json
import time
import uuid
from typing import Literal, Optional

EventStream = Literal["lifecycle", "retrieval", "assistant", "error"]

# 每個 runId 的 seq 計數器（process-local，重啟後從 0 開始；可改 Redis 跨 worker）
_seq_by_run: dict[str, int] = {}


def new_run_id() -> str:
    """生成一個全新的 runId，代表一次完整的問答任務"""
    return str(uuid.uuid4())


def emit_event(
    run_id: str,
    stream: EventStream,
    data: dict,
    session_key: Optional[str] = None,
) -> str:
    """
    產生一筆 SSE 封包字串。

    格式：
        data: {"runId": "...", "seq": 1, "stream": "lifecycle", "ts": 1234567890, ...}\n\n
    """
    seq = _seq_by_run.get(run_id, 0) + 1
    _seq_by_run[run_id] = seq

    payload = {
        "runId": run_id,
        "seq": seq,
        "stream": stream,
        "ts": int(time.time() * 1000),
        **data,
    }
    if session_key:
        payload["sessionKey"] = session_key

    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def emit_lifecycle(run_id: str, content: str, **kwargs) -> str:
    return emit_event(run_id, "lifecycle", {"type": "status", "content": content}, **kwargs)


def emit_sources(run_id: str, sources: list, **kwargs) -> str:
    return emit_event(run_id, "retrieval", {"type": "sources", "sources": sources}, **kwargs)


def emit_token(run_id: str, content: str, **kwargs) -> str:
    return emit_event(run_id, "assistant", {"type": "token", "content": content}, **kwargs)


def emit_suggestions(run_id: str, items: list[str], **kwargs) -> str:
    return emit_event(run_id, "assistant", {"type": "suggestions", "items": items}, **kwargs)


def emit_done(run_id: str, message_id: str, conversation_id: str, **kwargs) -> str:
    return emit_event(run_id, "lifecycle", {
        "type": "done",
        "message_id": message_id,
        "conversation_id": conversation_id,
    }, **kwargs)


def emit_error(run_id: str, error: str, code: Optional[str] = None, **kwargs) -> str:
    return emit_event(run_id, "error", {"type": "error", "error": error, "code": code}, **kwargs)


def clear_run(run_id: str):
    """清理完成的 run，避免 memory leak"""
    _seq_by_run.pop(run_id, None)
```

**修改 `app/api/v1/endpoints/chat.py`**，在 `chat_stream` 端點改用新工具：

```python
# 在 chat_stream 函數的 event_generator 中替換
from app.services.event_stream import new_run_id, emit_lifecycle, emit_sources, emit_token, emit_done, emit_error, clear_run

async def event_generator():
    run_id = new_run_id()
    session_key = str(current_user.tenant_id)
    try:
        yield emit_lifecycle(run_id, "正在搜尋知識庫...", session_key=session_key)
        # ... 後續邏輯
        yield emit_sources(run_id, ctx["sources"], session_key=session_key)
        async for chunk in orchestrator.stream_answer(...):
            yield emit_token(run_id, chunk, session_key=session_key)
        yield emit_done(run_id, str(ai_message.id), str(conversation.id), session_key=session_key)
    except Exception as e:
        yield emit_error(run_id, str(e), session_key=session_key)
    finally:
        clear_run(run_id)
```

**前端對應處理**（TypeScript 參考）：
```typescript
let lastSeq = 0;
eventSource.onmessage = (e) => {
  const event = JSON.parse(e.data);
  if (event.seq !== lastSeq + 1) {
    console.warn(`SSE gap detected: expected seq=${lastSeq+1}, got ${event.seq}`);
    // 可觸發 reconnect 或顯示警告
  }
  lastSeq = event.seq;
  // 依 event.stream 分流處理
  switch(event.stream) {
    case "lifecycle": handleStatus(event); break;
    case "retrieval": handleSources(event); break;
    case "assistant": handleToken(event); break;
    case "error":     handleError(event); break;
  }
};
```

---

## P1：Embedding Query Cache

### 問題根因

- Redis 目前只快取「查詢結果（5 個 chunk）」，不快取 embedding 本身
- 同一份文件重新上傳、相似問題反覆被問到，Voyage API 被重複呼叫
- 每次 KnowledgeBaseRetriever.search() 都呼叫 `voyage_client.embed()`（約 200-500ms）
- 文件處理時，同一段落（免責聲明、頁眉/頁腳）在多份文件中重複出現，導致重複嵌入

### OpenClaw 解法

**參考檔案**：`C:\Users\User\Desktop\openclaw\src\memory\manager.ts`

```typescript
const EMBEDDING_CACHE_TABLE = "embedding_cache"; // SQLite table
// key = hash(model + text) → 命中即跳過 API 呼叫
// 節省延遲與費用；特別適合「高重複性文字」（頁眉、免責聲明、固定段落）
```

### UniHR 轉用方案

**修改 `app/services/kb_retrieval.py`**：

```python
def _embed_query_cached(self, query: str) -> list[float]:
    """
    Query embedding with Redis cache.
    Cache key = sha256(model:query)[:16]
    TTL = 1 hour（query embedding 通常不需要太長）
    """
    import hashlib
    cache_key = f"emb:q:{hashlib.sha256(f'{settings.VOYAGE_MODEL}:{query}'.encode()).hexdigest()[:16]}"

    if self._redis:
        cached = self._redis.get(cache_key)
        if cached:
            return json.loads(cached)

    result = self.voyage_client.embed([query], model=settings.VOYAGE_MODEL)
    vec = result.embeddings[0]

    if self._redis:
        self._redis.setex(cache_key, 3600, json.dumps(vec))  # TTL=1h

    return vec
```

**文件處理端（`app/tasks/document_tasks.py`）加 chunk-level cache**：

```python
def embed_chunks_with_cache(chunks: list[str], voyage_client, redis_client=None) -> list[list[float]]:
    """
    批次 embedding，命中 cache 的 chunk 不重複呼叫 Voyage API。
    適合處理含有重複段落的文件（免責聲明、頁眉、固定格式）。
    """
    import hashlib

    cache_keys = [
        f"emb:c:{hashlib.sha256(f'{settings.VOYAGE_MODEL}:{chunk}'.encode()).hexdigest()[:16]}"
        for chunk in chunks
    ]

    embeddings = [None] * len(chunks)
    miss_indices = []

    # Cache lookup
    if redis_client:
        for i, key in enumerate(cache_keys):
            cached = redis_client.get(key)
            if cached:
                embeddings[i] = json.loads(cached)
            else:
                miss_indices.append(i)
    else:
        miss_indices = list(range(len(chunks)))

    # Batch embed cache misses
    if miss_indices:
        miss_texts = [chunks[i] for i in miss_indices]
        result = voyage_client.embed(miss_texts, model=settings.VOYAGE_MODEL)
        for idx, emb in zip(miss_indices, result.embeddings):
            embeddings[idx] = emb
            if redis_client:
                redis_client.setex(cache_keys[idx], 86400, json.dumps(emb))  # TTL=24h

    return embeddings
```

**Redis DB 規劃更新**（目前 db=0 Celery, db=1 檢索快取）：
- `db=2`：Embedding cache（Query + Chunk level）

---

## P1：Hybrid Search 可調權重（替換純 RRF）

### 問題根因

從 docs/reports/QUALITY_PERFORMANCE_REPORT.md 人工審查結果：
- **D2**（技術部平均月薪）：只找到 4 人，少了 2 人 → 語義向量召回不完整
- **D4**（年資最深員工）：回答謝雅玲 8.7 年，實際是 E005 張志豪 9.6 年 → 結構化表格 chunk 召回不足
- **D3**（資遣費計算）：計算邏輯依賴精確員工資料，若 chunk 遺漏則計算錯誤

問題根因：純 RRF 對「含員工編號/數值」的結構化查詢效果不如 BM25。

### OpenClaw 解法

**參考檔案**：`C:\Users\User\Desktop\openclaw\src\memory\hybrid.ts`

```typescript
// 加權線性融合（不是死板的 RRF）
score = vectorScore * vectorWeight + textScore * textWeight;
// 支援 candidateMultiplier：先取 maxResults × N 個候選，再 merge
// vectorWeight / textWeight 可由管理員在配置中調整
```

### UniHR 轉用方案

**修改 `app/services/kb_retrieval.py`**，新增自動權重偵測與可調參數：

```python
def _detect_optimal_weights(self, query: str) -> tuple[float, float]:
    """
    根據問題特徵自動調整 vector/keyword 融合權重。
    對應 OpenClaw 的 vectorWeight / textWeight 配置。

    Rules:
      - 含員工編號（E001~E999）或 3+ 位數字 → 重 BM25（keyword）
      - 含姓名 → 偏 BM25
      - 純法律/政策問題 → 重語意向量
    Returns:
      (vector_weight, text_weight) — 兩者加總為 1.0
    """
    import re
    has_employee_id = bool(re.search(r'[EeＥｅ]\d{3}', query))
    has_number      = bool(re.search(r'\d{4,}', query))  # 4位以上數字（金額/統編）
    has_name_hint   = bool(re.search(r'[\u4e00-\u9fff]{2,3}(?:先生|小姐|部門|課|組)', query))
    is_structural   = bool(re.search(r'平均|最高|最低|第幾|排名|列出', query))

    if has_employee_id or (has_number and is_structural):
        return 0.25, 0.75   # 重 BM25
    if has_name_hint:
        return 0.35, 0.65   # 偏 BM25
    return 0.70, 0.30        # 預設：重語意向量

def _weighted_hybrid_merge(
    self,
    semantic_results: list[dict],
    keyword_results: list[dict],
    vector_weight: float,
    text_weight: float,
    top_k: int,
) -> list[dict]:
    """
    加權線性融合（取代純 RRF）。
    對應 OpenClaw mergeHybridResults 的設計。
    """
    from collections import defaultdict
    merged: dict[str, dict] = {}

    # 先正規化 score 到 0~1
    def normalize(results, score_key):
        if not results:
            return results
        max_s = max(r.get(score_key, 0) for r in results) or 1.0
        for r in results:
            r[f"_norm_{score_key}"] = r.get(score_key, 0) / max_s
        return results

    semantic_results = normalize(semantic_results, "score")
    keyword_results  = normalize(keyword_results, "score")

    for r in semantic_results:
        cid = r.get("chunk_id") or r.get("id", "")
        merged[cid] = {**r, "_vscore": r.get("_norm_score", 0), "_kscore": 0.0}

    for r in keyword_results:
        cid = r.get("chunk_id") or r.get("id", "")
        if cid in merged:
            merged[cid]["_kscore"] = r.get("_norm_score", 0)
            # keyword snippet 通常更精準，優先覆蓋
            if r.get("content"):
                merged[cid]["content"] = r["content"]
        else:
            merged[cid] = {**r, "_vscore": 0.0, "_kscore": r.get("_norm_score", 0)}

    # 加權融合 score
    for cid, item in merged.items():
        item["score"] = item["_vscore"] * vector_weight + item["_kscore"] * text_weight

    sorted_results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    return sorted_results[:top_k]
```

**在 `search()` 方法中整合**：
```python
# 在 _hybrid_search 之後，RRF 之前加入
if mode == "hybrid":
    v_weight, k_weight = self._detect_optimal_weights(query)
    results = self._weighted_hybrid_merge(
        semantic_results=..., keyword_results=...,
        vector_weight=v_weight, text_weight=k_weight,
        top_k=top_k,
    )
```

**Tenant 級可配置**（存入 `FeaturePermission.config`）：
```json
{
  "feature": "retrieval",
  "config": {
    "vector_weight": 0.6,
    "text_weight": 0.4,
    "candidate_multiplier": 3
  }
}
```

---

## P1：文件 Embedding 批次重試（指數退避）

### 問題根因

`app/tasks/document_tasks.py` 呼叫 Voyage API 無重試機制：
- 任何暫時性網路抖動 → 文件 `status=failed`，必須手動重新上傳
- Voyage API 有 rate limit，批次上傳多文件時容易觸發

### OpenClaw 解法

**參考檔案**：`C:\Users\User\Desktop\openclaw\src\memory\manager.ts`

```typescript
const EMBEDDING_RETRY_MAX_ATTEMPTS = 3;
const EMBEDDING_RETRY_BASE_DELAY_MS = 500;
const EMBEDDING_RETRY_MAX_DELAY_MS = 8000;
const BATCH_FAILURE_LIMIT = 2;
// 批次失敗達 2 次 → 降級為單筆模式
```

### UniHR 轉用方案

**新增函數至 `app/tasks/document_tasks.py`**：

```python
import asyncio

async def embed_with_retry(
    texts: list[str],
    voyage_client,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
) -> list[list[float]]:
    """
    帶指數退避重試的 Voyage embedding。
    對應 OpenClaw EMBEDDING_RETRY_* 設計。

    失敗分類：
      - RateLimitError → 重試（等待較長）
      - APIError 5xx    → 重試（暫時性）
      - 其他            → 重試最多 max_attempts 次後 raise
    """
    import voyageai

    for attempt in range(max_attempts):
        try:
            result = voyage_client.embed(texts, model=settings.VOYAGE_MODEL)
            return result.embeddings

        except voyageai.error.RateLimitError:
            delay = min(max_delay, base_delay * (4 ** attempt))  # rate limit 退避更慢
            logger.warning(f"[Embedding] Rate limit hit, retry {attempt+1}/{max_attempts} after {delay:.1f}s")
            await asyncio.sleep(delay)

        except Exception as e:
            delay = min(max_delay, base_delay * (2 ** attempt))
            logger.warning(f"[Embedding] Error on attempt {attempt+1}/{max_attempts}: {e}, retry after {delay:.1f}s")
            if attempt == max_attempts - 1:
                raise
            await asyncio.sleep(delay)

    raise RuntimeError("Embedding failed after all retries")


async def embed_in_batches(
    texts: list[str],
    voyage_client,
    batch_size: int = 128,
    max_batch_failures: int = 2,
) -> list[list[float]]:
    """
    分批 embedding，批次連續失敗超過 max_batch_failures 次時降級為單筆模式。
    對應 OpenClaw BATCH_FAILURE_LIMIT 設計。
    """
    all_embeddings = []
    batch_failure_count = 0

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            if batch_failure_count >= max_batch_failures:
                # 降級：逐筆處理
                for text in batch:
                    embs = await embed_with_retry([text], voyage_client)
                    all_embeddings.extend(embs)
            else:
                embs = await embed_with_retry(batch, voyage_client)
                all_embeddings.extend(embs)
                batch_failure_count = 0  # 成功則重置計數
        except Exception:
            batch_failure_count += 1
            raise

    return all_embeddings
```

**修改 `process_document_task`**：將現有直接呼叫 `voyage_client.embed()` 包進 `embed_in_batches()`。

---

## P2：Feature Flag 記憶體快取

### 問題根因

每次 API request 呼叫 `is_flag_enabled()` → 都 SELECT DB。
Feature Flag 更新頻率極低（每天幾次），但查詢頻率極高（每次 chat/upload 都查詢）。

### OpenClaw 解法

Config 分類為 hot/restart/none，hot 項目透過事件通知 invalidate，不需要每次都讀磁碟/DB。

### UniHR 轉用方案

**修改 `app/services/feature_flags.py`**，加入記憶體 LRU cache：

```python
# app/services/feature_flags.py 新增 cache 層
import functools
import time
from threading import Lock

_FLAG_CACHE: dict[str, tuple[bool, float]] = {}  # key → (result, expire_ts)
_FLAG_CACHE_TTL = 30.0  # 秒
_FLAG_CACHE_LOCK = Lock()


def is_flag_enabled_cached(db, flag_key: str, tenant_id=None) -> bool:
    """
    帶 30 秒 TTL 的 in-process cache。
    熱點請求（chat endpoint 每次都查）從 DB query 降為 dict lookup。
    """
    cache_key = f"{flag_key}:{tenant_id}"
    now = time.monotonic()

    with _FLAG_CACHE_LOCK:
        if cache_key in _FLAG_CACHE:
            result, expire_ts = _FLAG_CACHE[cache_key]
            if now < expire_ts:
                return result

    # Cache miss → 查 DB
    result = is_flag_enabled(db, flag_key, tenant_id)

    with _FLAG_CACHE_LOCK:
        _FLAG_CACHE[cache_key] = (result, now + _FLAG_CACHE_TTL)

    return result


def invalidate_flag_cache(flag_key: str = None):
    """
    Feature Flag 更新時呼叫（在 admin API endpoint 的 PUT/POST handler 中）。
    flag_key=None 表示清除所有快取。
    """
    with _FLAG_CACHE_LOCK:
        if flag_key is None:
            _FLAG_CACHE.clear()
        else:
            keys_to_delete = [k for k in _FLAG_CACHE if k.startswith(f"{flag_key}:")]
            for k in keys_to_delete:
                del _FLAG_CACHE[k]
```

**在 admin Feature Flag 更新 endpoint 加入 invalidate**：
```python
# app/api/v1/endpoints/feature_flags.py 的 update 端點
from app.services.feature_flags import invalidate_flag_cache
# ...
invalidate_flag_cache(flag_key)  # 更新後立即清除 cache
```

---

## P2：Subsystem Logger 分類日誌

### 問題根因

所有 logger 用 `logging.getLogger(__name__)`，在 Grafana/ELK 中無法按子系統過濾。
QUALITY_PERFORMANCE_REPORT 顯示平均 48.9 秒延遲，但無法快速定位是「embedding」「retrieval」還是「Core API」哪段最耗時。

### OpenClaw 解法

**參考檔案**：`C:\Users\User\Desktop\openclaw\src\logging\subsystem.ts`

```typescript
// 建立有 subsystem 標籤的 logger
const log = createSubsystemLogger("memory");
const log = createSubsystemLogger("gateway/chat");
// 輸出：[memory] connected to SQLite
// 輸出：[gateway/chat] SSE stream started
```

### UniHR 轉用方案

**修改 `app/logging_config.py`**，加入 subsystem 支援：

```python
# app/logging_config.py 新增
import logging
from typing import Optional


class SubsystemLogger(logging.LoggerAdapter):
    """
    帶 subsystem 標籤的 Logger Adapter。
    對應 OpenClaw createSubsystemLogger。
    輸出格式：{"subsystem": "retrieval/hybrid", "message": "..."}（JSON 模式）
    或：[retrieval/hybrid] message（Console 模式）
    """
    def __init__(self, logger: logging.Logger, subsystem: str):
        super().__init__(logger, {"subsystem": subsystem})
        self.subsystem = subsystem

    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        extra["subsystem"] = self.subsystem
        kwargs["extra"] = extra
        return msg, kwargs

    def child(self, name: str) -> "SubsystemLogger":
        return SubsystemLogger(self.logger, f"{self.subsystem}/{name}")


def get_subsystem_logger(name: str, subsystem: str) -> SubsystemLogger:
    """
    取得帶 subsystem 標籤的 logger。

    使用範例：
        logger = get_subsystem_logger(__name__, "retrieval/hybrid")
        logger = get_subsystem_logger(__name__, "document/parser")
        logger = get_subsystem_logger(__name__, "chat/orchestrator")
    """
    base_logger = logging.getLogger(name)
    return SubsystemLogger(base_logger, subsystem)
```

**各模組替換**：

| 檔案 | 替換前 | 替換後 |
|------|--------|--------|
| `app/services/kb_retrieval.py` | `logger = logging.getLogger(__name__)` | `logger = get_subsystem_logger(__name__, "retrieval/hybrid")` |
| `app/services/chat_orchestrator.py` | `logging.getLogger(__name__)` | `get_subsystem_logger(__name__, "chat/orchestrator")` |
| `app/services/document_parser.py` | `logging.getLogger(__name__)` | `get_subsystem_logger(__name__, "document/parser")` |
| `app/tasks/document_tasks.py` | `logging.getLogger(__name__)` | `get_subsystem_logger(__name__, "document/task")` |
| `app/services/core_client.py` | `logging.getLogger(__name__)` | `get_subsystem_logger(__name__, "core/client")` |

**Prometheus 整合**：在 `app/middleware/metrics.py` 加入 `subsystem` label，讓 Grafana 能按子系統看延遲分布：

```python
REQUEST_LATENCY.labels(method=method, endpoint=endpoint, subsystem=subsystem).observe(duration)
```

---

## P2：RBAC Method Matrix 集中化

### 問題根因

權限邏輯散落在每個 endpoint 的 `Depends(require_admin)` / `Depends(require_hr)` — 進行安全審計時需逐一翻閱 18 個 endpoint 檔案。

### OpenClaw 解法

**參考檔案**：`C:\Users\User\Desktop\openclaw\src\gateway\server-methods.ts`

```typescript
// 集中定義，一眼看出所有端點的權限
const READ_METHODS  = new Set(["health", "sessions.list", ...])
const WRITE_METHODS = new Set(["chat.send", "node.invoke", ...])
const ADMIN_METHOD_PREFIXES = ["exec.approvals."]
```

### UniHR 轉用方案

**新增檔案**：`app/core/rbac_matrix.py`

```python
# app/core/rbac_matrix.py
"""
RBAC 端點權限矩陣 — 集中定義所有端點的角色要求。
對應 OpenClaw server-methods.ts 的 READ_METHODS / WRITE_METHODS / ADMIN_METHOD_PREFIXES。

審計時只需看這一個檔案，不需要翻 18 個 endpoint 檔案。
"""
from typing import FrozenSet

# ── 角色定義（口訣：owner > admin > hr > employee > viewer）──
ROLE_OWNER    = "owner"
ROLE_ADMIN    = "admin"
ROLE_HR       = "hr"
ROLE_EMPLOYEE = "employee"
ROLE_VIEWER   = "viewer"

# ── 角色組合（常用的 allowed_roles set）──
ALL_AUTHENTICATED:  FrozenSet[str] = frozenset([ROLE_OWNER, ROLE_ADMIN, ROLE_HR, ROLE_EMPLOYEE, ROLE_VIEWER])
STAFF_AND_ABOVE:    FrozenSet[str] = frozenset([ROLE_OWNER, ROLE_ADMIN, ROLE_HR, ROLE_EMPLOYEE])
HR_AND_ABOVE:       FrozenSet[str] = frozenset([ROLE_OWNER, ROLE_ADMIN, ROLE_HR])
ADMIN_AND_ABOVE:    FrozenSet[str] = frozenset([ROLE_OWNER, ROLE_ADMIN])
OWNER_ONLY:         FrozenSet[str] = frozenset([ROLE_OWNER])

# ── 端點權限矩陣 ──
# 格式：(router_prefix, http_method) → allowed_roles
# http_method = "GET" / "POST" / "PUT" / "DELETE" / "*"（所有方法）
ENDPOINT_ROLE_MATRIX: dict[tuple[str, str], FrozenSet[str]] = {
    # ── Documents ──
    ("documents", "GET"):    ALL_AUTHENTICATED,
    ("documents", "POST"):   HR_AND_ABOVE,          # 上傳文件
    ("documents", "DELETE"): ADMIN_AND_ABOVE,        # 刪除文件

    # ── Chat ──
    ("chat", "POST"):        STAFF_AND_ABOVE,        # 發送訊息（viewer 唯讀）
    ("chat", "GET"):         ALL_AUTHENTICATED,      # 查看歷史

    # ── Users ──
    ("users", "GET"):        HR_AND_ABOVE,
    ("users", "POST"):       ADMIN_AND_ABOVE,
    ("users", "PUT"):        ADMIN_AND_ABOVE,
    ("users", "DELETE"):     ADMIN_AND_ABOVE,

    # ── Departments ──
    ("departments", "GET"):  ALL_AUTHENTICATED,
    ("departments", "*"):    ADMIN_AND_ABOVE,

    # ── Analytics ──
    ("analytics", "GET"):    ADMIN_AND_ABOVE,

    # ── Audit ──
    ("audit", "GET"):        ADMIN_AND_ABOVE,

    # ── Company Admin（自助管理）──
    ("company", "GET"):      ADMIN_AND_ABOVE,
    ("company", "PUT"):      ADMIN_AND_ABOVE,

    # ── SSO ──
    ("auth/sso", "GET"):     ALL_AUTHENTICATED,
    ("auth/sso", "POST"):    ADMIN_AND_ABOVE,        # 建立/修改 SSO 配置
    ("auth/sso", "DELETE"):  ADMIN_AND_ABOVE,

    # ── Feature Flags ──
    ("feature-flags", "GET"): ALL_AUTHENTICATED,
    ("feature-flags", "*"):   frozenset(["superuser"]),  # 只有超管能修改 Feature Flag

    # ── Admin（平台超管）──
    ("admin", "*"):           frozenset(["superuser"]),

    # ── Subscription ──
    ("subscription", "GET"): ADMIN_AND_ABOVE,
    ("subscription", "*"):   OWNER_ONLY,

    # ── Regions ──
    ("regions", "GET"):      ADMIN_AND_ABOVE,
    ("regions", "*"):        frozenset(["superuser"]),

    # ── Custom Domains ──
    ("domains", "*"):        OWNER_ONLY,

    # ── Knowledge Base ──
    ("kb", "GET"):           STAFF_AND_ABOVE,
    ("kb", "POST"):          HR_AND_ABOVE,
    ("kb", "DELETE"):        ADMIN_AND_ABOVE,
}
```

---

## P2：路徑安全驗證（Path Traversal 防護）

### 問題根因

- `brand_logo_url` / `brand_favicon_url` 未驗證是否符合可信域名
- `Document.file_path` 欄位可能被手動寫入任意路徑
- 上傳路徑基於 `settings.UPLOAD_DIR`，但未強制驗證子路徑不逃逸

### OpenClaw 解法

**參考檔案**：`C:\Users\User\Desktop\openclaw\src\config\validation.ts`

```typescript
// avatar path 必須在 agent workspace 內
function isWorkspaceAvatarPath(value, workspaceDir): boolean {
  const relative = path.relative(workspaceRoot, path.resolve(workspaceRoot, value));
  return !relative.startsWith(".."); // 絕不允許走出 workspace
}
```

### UniHR 轉用方案

**新增檔案**：`app/core/path_security.py`

```python
# app/core/path_security.py
"""
路徑安全驗證工具集 — 仿 OpenClaw config/validation.ts 設計
防止：
  - Path Traversal（../../etc/passwd）
  - SSRF via brand URL（intranet URLs）
  - 任意檔案讀取（透過 file_path 欄位）
"""
from pathlib import Path
from urllib.parse import urlparse
from fastapi import HTTPException, status
from app.config import settings

# 允許的 brand URL 域名（可設定為空 list 表示不限制）
TRUSTED_CDN_DOMAINS: list[str] = []  # e.g. ["cdn.example.com", "s3.amazonaws.com"]


def assert_within_upload_dir(path_str: str) -> Path:
    """
    驗證路徑必須在 UPLOAD_DIR 內，防止 Path Traversal。
    對應 OpenClaw isWorkspaceAvatarPath。
    """
    upload_root = Path(settings.UPLOAD_DIR).resolve()
    target = (upload_root / path_str).resolve()

    # 確認目標路徑不逃逸出 upload_root
    try:
        target.relative_to(upload_root)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file path: path traversal detected",
        )
    return target


def validate_brand_url(url: str, field_name: str = "url") -> str:
    """
    驗證 brand logo/favicon URL：
    1. 必須是 https://
    2. 不能是私有 IP（防 SSRF）
    3. 長度限制 500 字元
    """
    if not url:
        return url

    if len(url) > 500:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} is too long (max 500 chars)",
        )

    parsed = urlparse(url)

    # 強制 HTTPS
    if parsed.scheme not in ("https",):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must use https://",
        )

    # 防 SSRF：不允許私有 IP / localhost
    hostname = parsed.hostname or ""
    _BLOCKED_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    _PRIVATE_PREFIXES = ("10.", "172.16.", "172.17.", "192.168.", "169.254.")

    if hostname in _BLOCKED_HOSTNAMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} cannot point to localhost",
        )
    if any(hostname.startswith(p) for p in _PRIVATE_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} cannot point to private network",
        )

    # 若有設定信任域名白名單，則強制驗證
    if TRUSTED_CDN_DOMAINS and hostname not in TRUSTED_CDN_DOMAINS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} domain not in trusted list",
        )

    return url
```

**應用位置**：
- `app/api/v1/endpoints/documents.py`：`upload_document()` 中儲存 `file_path` 前呼叫 `assert_within_upload_dir()`
- `app/api/v1/endpoints/admin.py` 或 `tenant_admin.py`：更新 brand URL 時呼叫 `validate_brand_url()`

---

## 不適合轉用的部分

| OpenClaw 功能 | 不轉用原因 | 若未來需要可參考 |
|--------------|------------|----------------|
| **Plugin Manifest System** | UniHR 是封閉式 SaaS，核心邊界固定，外掛擴充非當前需求 | 若未來開放 ISV 整合可借鑑 |
| **Multi-channel Adapter**（Telegram/Discord/Slack）| UniHR 是 Web 專用 HR 平台 | 若要加 LINE 通知可借鑑 adapter 模式 |
| **Exec Approval Manager** | UniHR 無 CLI 執行能力 | 可借鑑為「文件審核 workflow」pattern |
| **Config Hot Reload（chokidar）** | Python 後端用 DB config，不監聽 YAML 檔案 | 概念可用於 Feature Flag cache invalidation |
| **Declarative Bindings Router** | UniHR 路由基於 tenant_id，不需要 account/channel matching | |
| **SQLite-vec local embedding** | UniHR 已有 pgvector in PostgreSQL | 離線/邊緣部署場景可考慮 |
| **QMD Manager（外部向量進程）** | UniHR 已整合 pgvector，不需要外部進程 | |

---

## 升級優先排序總表

| 優先 | 功能 | 新增/修改檔案 | 預估工時 | 直接解決的問題 |
|------|------|-------------|---------|--------------|
| **P0** | LLM Failover + Cooldown | `app/services/llm_failover.py`（新）<br>`app/services/chat_orchestrator.py`（改）<br>`app/services/core_client.py`（改）<br>`app/config.py`（改） | 1 天 | Core API rate limit；平均延遲從 48.9s 降低；系統可用性提升 |
| **P0** | SSE runId/seq 保序 | `app/services/event_stream.py`（新）<br>`app/api/v1/endpoints/chat.py`（改） | 0.5 天 | 前端重連後漏事件；多輪串流一致性 |
| **P1** | Embedding Query Cache | `app/services/kb_retrieval.py`（改） | 0.5 天 | 降低 Voyage 費用 15-30%；重複問題加速 |
| **P1** | Hybrid Search 可調權重 | `app/services/kb_retrieval.py`（改） | 1 天 | D2/D4 結構化查詢錯誤；人工正確率從 79% 提升 |
| **P1** | Embedding 批次重試 | `app/tasks/document_tasks.py`（改） | 0.5 天 | 文件處理 `status=failed` 機率降低 |
| **P2** | Feature Flag 記憶體快取 | `app/services/feature_flags.py`（改）<br>`app/api/v1/endpoints/feature_flags.py`（改）| 0.5 天 | 每次 chat request 少 1 次 DB 查詢 |
| **P2** | Subsystem Logger | `app/logging_config.py`（改）<br>各服務檔案（改）| 0.5 天 | Grafana 延遲根因分析能力 |
| **P2** | RBAC Matrix 集中化 | `app/core/rbac_matrix.py`（新） | 1 天 | 安全審計可讀性；降低漏設權限風險 |
| **P2** | Path Traversal 驗證 | `app/core/path_security.py`（新）<br>`app/api/v1/endpoints/documents.py`（改）| 0.5 天 | 安全加固（SSRF / 路徑穿越）|

**總預估工時**：約 **6 個工作天**（P0 = 1.5 天，P1 = 2 天，P2 = 2.5 天）

---

## 附：OpenClaw 原始碼對應位置

| 本文提及的設計 | OpenClaw 原始碼位置 |
|--------------|-------------------|
| Model Fallback | `src/agents/model-fallback.ts` |
| Auth Profile Cooldown | `src/agents/auth-profiles/usage.ts` |
| Agent Events（runId/seq） | `src/infra/agent-events.ts` |
| Hybrid Search（加權融合）| `src/memory/hybrid.ts` |
| Memory Index Manager | `src/memory/manager.ts` |
| Embedding Provider Fallback | `src/memory/embeddings.ts` |
| Config Hot Reload Rules | `src/gateway/config-reload.ts` |
| Gateway RBAC Method Matrix | `src/gateway/server-methods.ts` |
| Path/Avatar 安全驗證 | `src/config/validation.ts` |
| Subsystem Logger | `src/logging/subsystem.ts` |
| Exec Approval Manager | `src/gateway/exec-approval-manager.ts` |
| Declarative Bindings | `src/routing/bindings.ts` |
