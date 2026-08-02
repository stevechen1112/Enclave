import logging
import json
import asyncio
from datetime import date
from typing import Dict, Any, List, Optional, AsyncGenerator
from uuid import UUID
import uuid
from app.config import settings
from app.services.deployment_mode import resolve_runtime_profiles_no_db
from app.services.kb_retrieval import KnowledgeBaseRetriever
from app.services.structured_answers import try_structured_answer
from app.gateway.contracts import SearchDomain
from app.gateway.runtime import get_configured_gateway_router
from app.services.unified_retriever import UnifiedRetriever

logger = logging.getLogger(__name__)


def _get_unified_retriever() -> UnifiedRetriever:
    return UnifiedRetriever(get_configured_gateway_router())

# ── 可選依賴 ──
try:
    import openai as openai_lib
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False


class ChatOrchestrator:
    """
    聊天協調器（RAG Generation 層）

    負責：
    1. 查詢企業內部知識庫（KB Retrieval）
    2. 使用 LLM 根據檢索結果生成上下文感知的回答
    3. 附帶來源引用
    4. 支援串流生成 (T7-1) 與多輪對話 (T7-2)
    """

    SYSTEM_PROMPT = """你是企業私有知識庫的 AI 問答助理，專門根據組織內部文件回答問題。

回答規則：
1. **只根據下方提供的參考資料回答**，不要自行捏造或引用未提供的內容
2. 若參考資料中有多份文件涉及同一問題，綜合各份文件給出最完整的回答
3. 若參考資料中出現相互矛盾的內容，明確指出矛盾之處，並說明各自的依據
4. 若參考資料不足以回答問題，坦白說明「目前知識庫中沒有足夠的相關文件」
5. 引用文件時，請標注文件名稱（例如：根據《XXX 合約》第 X 條）
6. 使用結構化格式（標題、條列）讓回答清楚易讀
7. 需要數值計算時，列出公式與代入值，嚴格依公式計算
8. 使用繁體中文回答"""

    FOLLOWUP_PROMPT = """

在回答的最後，請另起一行輸出 2-3 個使用者可能會追問的建議問題，格式：
[建議問題]
1. ...
2. ...
3. ..."""
    
    def __init__(self):
        self.kb_retriever = KnowledgeBaseRetriever()
        runtime = resolve_runtime_profiles_no_db()

        # LLM client（依 LLM_PROVIDER 決定後端）— 用於 RAG 問答（需要強 LLM）
        self._openai = None
        self._openai_async = None
        self._llm_model = "gpt-4o-mini"

        main_cfg = runtime.get("main", {})
        provider = str(main_cfg.get("provider", getattr(settings, "LLM_PROVIDER", "openai"))).lower()
        main_model = str(main_cfg.get("model", ""))

        if _HAS_OPENAI:
            if provider == "gemini":
                api_key = getattr(settings, "GEMINI_API_KEY", "")
                if api_key:
                    _base = "https://generativelanguage.googleapis.com/v1beta/openai/"
                    self._openai = openai_lib.OpenAI(api_key=api_key, base_url=_base)
                    self._openai_async = openai_lib.AsyncOpenAI(api_key=api_key, base_url=_base)
                    self._llm_model = main_model or getattr(settings, "GEMINI_MODEL", "gemini-3-flash-preview")
            elif provider == "openai":
                api_key = getattr(settings, "OPENAI_API_KEY", "")
                if api_key:
                    self._openai = openai_lib.OpenAI(api_key=api_key)
                    self._openai_async = openai_lib.AsyncOpenAI(api_key=api_key)
                    self._llm_model = main_model or getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")
            elif provider == "ollama":
                ollama_url = str(main_cfg.get("base_url", getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")))
                self._openai = openai_lib.OpenAI(api_key="ollama", base_url=f"{ollama_url.rstrip('/')}/v1/")
                self._openai_async = openai_lib.AsyncOpenAI(api_key="ollama", base_url=f"{ollama_url.rstrip('/')}/v1/")
                self._llm_model = main_model or getattr(settings, "OLLAMA_MODEL", "llama3.2")

        # Internal LLM（用於 contextualize 改寫等輕量任務，走本地 Ollama 省錢）
        self._internal_async = None
        self._internal_model = None
        internal_cfg = runtime.get("internal", {})
        internal_provider = str(internal_cfg.get("provider", getattr(settings, "INTERNAL_LLM_PROVIDER", "ollama"))).lower()

        if _HAS_OPENAI and internal_provider == "ollama":
            ollama_url = str(internal_cfg.get("base_url", getattr(settings, "OLLAMA_SCAN_URL", "http://host.docker.internal:11434")))
            self._internal_model = str(internal_cfg.get("model", getattr(settings, "INTERNAL_OLLAMA_MODEL", "gemma3:27b")))
            self._internal_async = openai_lib.AsyncOpenAI(
                api_key="ollama",  # Ollama 不需要真實 key
                base_url=f"{ollama_url.rstrip('/')}/v1/",
            )
            logger.info("ChatOrchestrator internal LLM: Ollama(%s @ %s)", self._internal_model, ollama_url)
        elif internal_provider == "gemini":
            # 內部任務走 Gemini，使用獨立的輕量模型（可與主 LLM 不同）
            api_key = getattr(settings, "GEMINI_API_KEY", "")
            _base = "https://generativelanguage.googleapis.com/v1beta/openai/"
            if _HAS_OPENAI and api_key:
                self._internal_async = openai_lib.AsyncOpenAI(api_key=api_key, base_url=_base)
            else:
                self._internal_async = self._openai_async
            self._internal_model = str(internal_cfg.get("model", getattr(settings, "INTERNAL_GEMINI_MODEL", "gemini-3.1-flash-lite-preview")))
            logger.info("ChatOrchestrator internal LLM: Gemini(%s)", self._internal_model)
        elif internal_provider == "openai":
            # 內部任務走 OpenAI，使用獨立模型
            self._internal_async = self._openai_async
            self._internal_model = str(internal_cfg.get("model", getattr(settings, "INTERNAL_OPENAI_MODEL", "gpt-4o-mini")))
            logger.info("ChatOrchestrator internal LLM: OpenAI(%s)", self._internal_model)
        else:
            # 其他未知 provider — 退回主 LLM 客戶端
            self._internal_async = self._openai_async
            self._internal_model = self._llm_model

    # ──────────── T7-0: 檢索層（與生成解耦） ────────────

    async def retrieve_context(
        self,
        tenant_id: UUID,
        question: str,
        top_k: int = 5,
        authz = None,  # Phase 0: AuthorizationContext
        use_gateway: bool = True,
    ) -> Dict[str, Any]:
        """
        純檢索：查詢企業內部知識庫，回傳結構化上下文。

        優先經 Gateway/UnifiedRetriever 聚合；失敗時回退 kb_retrieval。
        """
        request_id = str(uuid.uuid4())
        company_policy_result: Dict[str, Any] = {"status": "error", "results": []}

        if authz is None:
            return self._build_context(
                question=question,
                company_policy={"status": "error", "error": "authz_required", "results": []},
                request_id=request_id,
            )

        from app.services.retrieval_facade import get_retrieval_facade
        facade = get_retrieval_facade()

        if use_gateway:
            try:
                retrieved = await facade.search_gateway(
                    authz=authz,
                    query=question,
                    top_k=top_k,
                    domain=SearchDomain.HYBRID,
                )
                # CitationBuilder emits citations in the same order as the results
                # it was built from; match each hit to its own citation by index so
                # a hit never inherits another hit's lineage.
                all_citations = list(retrieved.citations or [])
                results = []
                for i, r in enumerate(retrieved.results):
                    c = all_citations[i] if i < len(all_citations) else None
                    results.append(
                        {
                            "id": r.get("id"),
                            "content": r.get("content") or r.get("text") or "",
                            "score": r.get("score"),
                            "document_id": r.get("document_id"),
                            "filename": (r.get("metadata") or {}).get("filename", ""),
                            "chunk_index": (r.get("metadata") or {}).get("chunk_index"),
                            "source": r.get("provider"),
                            "citations": (
                                [
                                    {
                                        "citation_id": c.citation_id,
                                        "document_id": str(c.canonical_document_id),
                                        "document_revision": c.document_revision,
                                        "provider": c.provider,
                                    }
                                ]
                                if c is not None
                                else []
                            ),
                        }
                    )
                gw_status = getattr(retrieved, "gateway_status", None) or "success"
                company_policy_result = {
                    "status": "success",
                    "results": results,
                    "retrieval_mode": "gateway",
                    # partial adapter failures are degraded — do not claim full search.
                    "degraded": gw_status == "partial",
                    # A6: surface which providers actually answered for the audit trace.
                    "providers_called": list(
                        getattr(getattr(retrieved, "audit_trail", None), "providers_called", None)
                        or []
                    ),
                }
            except Exception as exc:
                logger.warning("Gateway retrieval failed, fallback to canonical facade: %s", exc)

        if company_policy_result.get("status") != "success":
            try:
                loop = asyncio.get_event_loop()
                retrieved = await loop.run_in_executor(
                    None,
                    lambda: facade.search(
                        authz=authz,
                        query=question,
                        top_k=top_k,
                    ),
                )
                # Preserve citation lineage on fallback the same way as gateway path.
                all_citations = list(retrieved.citations or [])
                fallback_results = []
                for i, r in enumerate(retrieved.results):
                    c = all_citations[i] if i < len(all_citations) else None
                    row = dict(r) if isinstance(r, dict) else {
                        "id": getattr(r, "id", None),
                        "content": getattr(r, "content", None) or getattr(r, "text", None) or "",
                        "score": getattr(r, "score", None),
                        "document_id": getattr(r, "document_id", None),
                    }
                    if c is not None:
                        row["citations"] = [{
                            "citation_id": c.citation_id,
                            "document_id": str(c.canonical_document_id),
                            "document_revision": c.document_revision,
                            "provider": c.provider,
                        }]
                    fallback_results.append(row)
                # Honest degraded signal: gateway unavailable → canonical-only
                company_policy_result = {
                    "status": "success",
                    "results": fallback_results,
                    "retrieval_mode": "canonical_fallback",
                    "degraded": True,
                    "providers_called": ["document"],
                }
            except Exception as e:
                company_policy_result = {
                    "status": "error",
                    "error": str(e),
                    "results": [],
                    "retrieval_mode": "error",
                    "degraded": True,
                }

        return self._build_context(
            question=question,
            company_policy=company_policy_result,
            request_id=request_id,
        )

    @staticmethod
    def _merge_policy_results(
        base: List[Dict[str, Any]],
        extra: List[Dict[str, Any]],
        max_results: int,
    ) -> List[Dict[str, Any]]:
        seen = set()
        merged: List[Dict[str, Any]] = []
        for item in extra + base:
            key = item.get("id") or f"{item.get('document_id')}:{item.get('chunk_index')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= max_results:
                break
        return merged

    def _build_context(
        self,
        question: str,
        company_policy: Dict[str, Any],
        request_id: str,
    ) -> Dict[str, Any]:
        """將 raw 檢索結果組裝為結構化 context dict。"""
        has_policy = (
            company_policy.get("status") == "success"
            and len(company_policy.get("results", [])) > 0
        )

        retrieval_mode = company_policy.get("retrieval_mode") or "canonical"
        degraded = bool(company_policy.get("degraded"))
        context: Dict[str, Any] = {
            "request_id": request_id,
            "question": question,
            "has_policy": has_policy,
            "company_policy_raw": None,
            "context_parts": [],
            "sources": [],
            "retrieval": {
                "mode": retrieval_mode,
                "degraded": degraded,
                "request_id": request_id,
                "providers_called": list(company_policy.get("providers_called") or []),
                "label": (
                    "僅使用本機主索引（外部來源／Gateway 暫時不可用）"
                    if degraded and retrieval_mode == "canonical_fallback"
                    else "已搜尋可存取知識"
                    if has_policy
                    else "未找到可存取證據"
                ),
            },
            "disclaimer": "本回答由 AI 根據知識庫文件生成，僅供參考。如有重要決策，請以正式文件為準。",
        }

        if has_policy:
            top_results = company_policy["results"][:5]
            context["company_policy_raw"] = {
                "content": top_results[0].get("content") or "",
                "source": top_results[0].get("filename") or "",
                "relevance_score": top_results[0].get("score") or 0,
                "all_results": [
                    {
                        "content": (r.get("content") or "")[:500],
                        "filename": r.get("filename") or "",
                        "score": r.get("score") or 0,
                    }
                    for r in top_results
                ],
            }
            for r in top_results:
                citations = r.get("citations") or []
                cite0 = citations[0] if citations else {}
                meta = r.get("metadata") or {}
                revision = (
                    cite0.get("document_revision")
                    or r.get("document_revision")
                    or meta.get("document_revision")
                    or meta.get("version")
                )
                page = (
                    r.get("page")
                    if r.get("page") is not None
                    else meta.get("page")
                    if meta.get("page") is not None
                    else meta.get("page_number")
                )
                context["sources"].append({
                    "type": "policy",
                    "title": r.get("filename") or meta.get("filename") or "",
                    "snippet": (r.get("content") or "")[:200],
                    "score": r.get("score") or 0,
                    "document_id": str(r.get("document_id") or cite0.get("document_id") or "") or None,
                    "document_revision": revision,
                    "chunk_index": r.get("chunk_index") if r.get("chunk_index") is not None else meta.get("chunk_index"),
                    "provider": r.get("source") or r.get("provider") or cite0.get("provider"),
                    "updated_at": meta.get("updated_at") or r.get("updated_at"),
                    "page": page,
                    "accessible": True,
                })
            for i, r in enumerate(top_results, 1):
                content = r.get("content") or ""
                filename = r.get("filename") or ""
                score = r.get("score") or 0
                context["context_parts"].append(
                    f"【文件 #{i}】（來源：{filename}，相關度：{score:.2f}）\n{content}"
                )

        return context

    async def stream_answer(
        self,
        question: str,
        context: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
        include_followup: bool = True,
    ) -> AsyncGenerator[str, None]:
        """
        串流生成 LLM 回答（SSE 用）。

        yield 每個 token chunk，前端可逐字渲染。
        若 LLM 不可用，則 yield 整段 fallback。
        """
        if not self._openai_async or not context["has_policy"]:
            yield self._fallback_answer(context)
            return

        messages = self._build_llm_messages(
            question, context, history=history, include_followup=include_followup
        )

        try:
            from app.services.openai_compat import chat_completion_kwargs

            base_max = int(getattr(settings, "OPENAI_MAX_TOKENS", 1500) or 1500)
            max_tokens = max(base_max, 4000)
            response = await self._openai_async.chat.completions.create(
                messages=messages,
                **chat_completion_kwargs(
                    self._llm_model,
                    max_tokens=max_tokens,
                    temperature=getattr(settings, "OPENAI_TEMPERATURE", 0.3),
                    stream=True,
                ),
            )
            produced = False
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    produced = True
                    yield delta.content
            if not produced:
                logger.warning("LLM stream produced no content tokens; emitting fallback notice")
                yield (
                    "模型未產出可讀答案（可能將回應額度用在內部推理）。"
                    "請縮小問題範圍，或改問可直接從文件摘錄的事實。"
                )
        except Exception as e:
            logger.warning("LLM 串流生成失敗，回退到模板: %s", e)
            yield self._fallback_answer(context)

    # ──────────── T7-2: 多輪對話支援 ────────────

    # 需要上下文補全的代名詞／指示詞
    _CONTEXT_PRONOUNS = ("他", "她", "它", "他的", "她的", "他們", "她們",
                         "這個人", "那個人", "此人", "該員工", "同一", "上述", "前述",
                         "其中", "這些", "那些", "上面", "裡面", "哪些",
                         "這個", "那個", "該", "以上", "剛才")

    async def contextualize_query(
        self, query: str, history: List[Dict[str, str]]
    ) -> str:
        """
        用 LLM 將含代名詞/省略主詞的查詢改寫為獨立查詢。
        優先使用 internal LLM（本地 Ollama）省錢，退回主 LLM 客戶端。
        若歷史為空、LLM 不可用、或問題不含指代詞，直接回傳原 query。
        """
        # 選擇內部 LLM（Ollama）或退回主 LLM
        client = self._internal_async or self._openai_async
        model = self._internal_model or self._llm_model

        if not history or not client:
            return query

        # 智慧跳過：問題不含代名詞/指示詞時無需 LLM 改寫（節省 ~0.9s）
        if not any(p in query for p in self._CONTEXT_PRONOUNS):
            return query

        messages = [
            {
                "role": "system",
                "content": (
                    "根據對話歷史，將使用者的最新問題改寫為一個獨立、完整的查詢。"
                    "只輸出改寫後的查詢，不要解釋。如果問題已經夠明確，直接原樣輸出。"
                ),
            },
            *[{"role": m["role"], "content": m["content"]} for m in history[-4:]],
            {"role": "user", "content": query},
        ]

        try:
            from app.services.openai_compat import chat_completion_kwargs

            response = await client.chat.completions.create(
                messages=messages,
                **chat_completion_kwargs(
                    model,
                    max_tokens=200,
                    temperature=0,
                ),
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("查詢改寫失敗: %s", e)
            return query

    # ──────────── 向下相容：保留原 process_query ────────────

    async def process_query(
        self,
        tenant_id: UUID,
        question: str,
        top_k: int = settings.RETRIEVAL_TOP_K,
        conversation_id: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        authz = None,  # Phase 0: AuthorizationContext
    ) -> Dict[str, Any]:
        """
        處理用戶查詢（非串流，向下相容）。
        
        新增 conversation_id / history 參數以支援多輪對話。
        Phase 0: 接受 AuthorizationContext 做 ACL 過濾。
        """
        structured = try_structured_answer(tenant_id, question, history=history)
        if structured:
            return {
                "request_id": str(uuid.uuid4()),
                "question": question,
                "company_policy": None,
                "answer": structured.answer,
                "sources": structured.sources,
                "notes": ["使用結構化資料直接計算"],
                "disclaimer": "本回答由 AI 根據知識庫文件生成，僅供參考。如有重要決策，請以正式文件為準。",
            }
        # 查詢改寫（多輪）
        effective_question = question
        if history:
            effective_question = await self.contextualize_query(question, history)

        # 檢索（Phase 0: 傳遞 authz）
        ctx = await self.retrieve_context(
            tenant_id=tenant_id,
            question=effective_question,
            top_k=top_k,
            authz=authz,
        )

        # 生成回答（非串流）
        result = {
            "request_id": ctx["request_id"],
            "question": question,
            "company_policy": ctx["company_policy_raw"],
            "answer": "",
            "sources": ctx["sources"],
            "notes": [],
            "disclaimer": ctx["disclaimer"],
            # A6: sync chat path must persist providers_called via RetrievalTrace
            "retrieval": ctx.get("retrieval") or {},
        }

        if self._openai and ctx["has_policy"]:
            try:
                result["answer"] = self._generate_answer_sync(
                    question, ctx, history=history
                )
                result["notes"].append("由 AI 根據檢索結果生成回答")
            except Exception as e:
                logger.warning(f"LLM 回答生成失敗，回退到模板: {e}")
                result["answer"] = self._fallback_answer(ctx)
                result["notes"].append("LLM 暫時無法使用，以結構化格式呈現")
        else:
            result["answer"] = self._fallback_answer(ctx)
            if not ctx["has_policy"]:
                result["notes"].append("未找到相關資訊")

        return result

    # ──────────── LLM Messages 組裝（共用） ────────────

    def _build_llm_messages(
        self,
        question: str,
        context: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
        include_followup: bool = True,
    ) -> List[Dict[str, str]]:
        """組裝 LLM 的 messages 陣列（含歷史 + 檢索上下文）。"""
        today_str = f"{date.today().year}年{date.today().month}月{date.today().day}日"
        system_content = f"今天日期：{today_str}\n\n" + self.SYSTEM_PROMPT
        if include_followup:
            system_content += self.FOLLOWUP_PROMPT

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_content}
        ]

        # 注入歷史（Token 預算管理）
        if history:
            max_history_tokens = 2000
            total_tokens = 0
            history_msgs = []
            for msg in reversed(history):
                # 粗估 1 中文字 ≈ 2 tokens
                msg_tokens = len(msg["content"])
                if total_tokens + msg_tokens > max_history_tokens:
                    break
                history_msgs.insert(0, {"role": msg["role"], "content": msg["content"]})
                total_tokens += msg_tokens
            messages.extend(history_msgs)

        context_text = "\n\n".join(context["context_parts"])
        history_summary = self._format_history_summary(history)
        calc_guidance = self._build_calc_guidance(question)
        user_content = f"問題：{question}\n\n參考資料：\n{context_text}\n\n請根據上述參考資料回答問題。"
        if history_summary:
            user_content = f"對話歷史摘要：\n{history_summary}\n\n" + user_content
        if calc_guidance:
            user_content += f"\n\n計算與判斷提示：\n{calc_guidance}"
        # 明確列出已找到的法條，要求 LLM 逐一引用
        law_sources = [
            s["title"] for s in context.get("sources", [])
            if s.get("type") == "law" and "Core API" not in s.get("title", "")
        ]
        if law_sources:
            user_content += (
                f"\n\n⚠️ 以下法條已在參考資料中明確標示，請務必在回答中引用（不得省略）："
                f"{'、'.join(law_sources)}"
            )
        messages.append({"role": "user", "content": user_content})

        return messages

    # ──────────── 同步生成（相容原介面） ────────────

    def _generate_answer_sync(
        self,
        question: str,
        context: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """同步 LLM 生成回答（非串流）。"""
        from app.services.openai_compat import chat_completion_kwargs

        messages = self._build_llm_messages(question, context, history=history)
        # gpt-5 系會把 completion budget 先花在 reasoning；複雜題 1500 常不夠留下正文
        base_max = int(getattr(settings, "OPENAI_MAX_TOKENS", 1500) or 1500)
        budgets = [base_max]
        if base_max < 4000:
            budgets.append(4000)

        last_finish = None
        last_reasoning = 0
        for max_tokens in budgets:
            response = self._openai.chat.completions.create(
                messages=messages,
                **chat_completion_kwargs(
                    self._llm_model,
                    max_tokens=max_tokens,
                    temperature=getattr(settings, "OPENAI_TEMPERATURE", 0.3),
                ),
            )
            choice = response.choices[0]
            content = (choice.message.content or "").strip()
            last_finish = choice.finish_reason
            usage = getattr(response, "usage", None)
            details = getattr(usage, "completion_tokens_details", None) if usage else None
            last_reasoning = int(getattr(details, "reasoning_tokens", 0) or 0) if details else 0
            if content:
                return content
            logger.warning(
                "LLM returned empty content (finish=%s reasoning_tokens=%s max_tokens=%s); retry/fallback",
                last_finish,
                last_reasoning,
                max_tokens,
            )

        # 推理耗盡預算仍無正文：不要回空字串假裝成功
        if last_finish == "length" and last_reasoning > 0:
            return (
                "模型在推理階段用盡了回應額度，未能產出可讀答案。"
                "請縮小問題範圍，或改問可直接從文件摘錄的事實。"
                "（若涉及 Excel 公式計算結果，亦可能因檔案未含快取值而無法直接得出數字。）"
            )
        return self._fallback_answer(context)

    @staticmethod
    def _build_calc_guidance(question: str) -> str:
        today = date.today()
        today_str = f"{today.year}年{today.month}月{today.day}日"
        hints: List[str] = []
        if "特休" in question or "特別休假" in question:
            hints.append("特休天數依勞基法第38條，按『實際到職日』計算年資，而非問題敘述中的概算。")
            hints.append("年資區間：未滿6個月=0天，6個月以上未滿1年=3天，1年=7天，2年=10天，3年=14天，5年=15天，10年以上每年+1天(最多30天)。")
            hints.append(f"若問題含有具體到職日期，請計算到今天（{today_str}）的正確年資後再查對照表。")
        if "資遣費" in question:
            hints.append("資遣費公式：年資(年) × 0.5 × 月平均工資。不要把月薪除以30。")
            hints.append("年資若含月份，需換算為年並可四捨五入到 0.5 年再計算。")
        if "加班" in question:
            hints.append("時薪計算：時薪 = 月薪 / 30 / 8（勞基法基準）。")
            hints.append("平日加班費：前 2 小時每小時 × 1.34 倍，第 3 小時起每小時 × 1.67 倍。")
            hints.append("休息日加班費：前 2 小時每小時 × 1.34 倍，第 3-8 小時每小時 × 1.67 倍，第 9 小時起 × 2.67 倍。")
            hints.append("計算時必須分段計算，不可把全部時數都乘同一倍率。例如：平日加班 4 小時 = 前 2 小時 × 1.34 + 後 2 小時 × 1.67。")
        if "平均" in question and ("薪" in question or "月薪" in question):
            hints.append("平均值需使用所有符合條件的資料列，不要只取前幾筆。")
        if "占比" in question or "比例" in question:
            hints.append("統計題請逐一計數並核對總數後再計算比例。")
        if "年資最深" in question or ("最深" in question and "年資" in question):
            hints.append("最深年資需比對完整名冊後再下結論。")
        if "加班" in question and ("合法" in question or "合法嗎" in question):
            hints.append("若題目只給單一倍數（如 1.5 倍），視為前 2 小時標準；可判定合法，但提醒超過 2 小時需 1.67 倍。")
        if "勞保" in question:
            hints.append("若薪資條已列出勞保自付金額，直接引用該數值。")
        if "颱風" in question or "停班停課" in question:
            hints.append("颱風停班停課屬行政建議性質，雇主可視需要出勤，但不得不利處分；若出勤需依規定給付。")
        if "責任制" in question:
            hints.append("一般工程師通常不適用責任制，仍應依工時規定與加班費規定。")
        if "年終獎金" in question and "工資" in question:
            hints.append("年終獎金是否屬工資需視是否為經常性/固定性給付與契約約定，通常需個案判斷。")
        if "離職" in question and "資遣費" in question:
            hints.append("自請離職無資遣費；資遣費僅適用雇主依法資遣情況。")
        if "喪假" in question and "配偶" in question and "祖父母" in question:
            hints.append("配偶的祖父母喪假法定 3 天；如公司內規給更高天數可視為優於法令。")
        if not hints:
            return ""
        return "\n".join(f"- {h}" for h in hints)

    @staticmethod
    def _format_history_summary(history: Optional[List[Dict[str, str]]]) -> str:
        if not history:
            return ""
        kept = history[-2:]
        lines = []
        for msg in kept:
            role = msg.get("role", "user")
            content = msg.get("content", "").strip()
            if not content:
                continue
            lines.append(f"[{role}] {content[:200]}")
        return "\n".join(lines)

    # ──────────── Fallback ────────────

    @staticmethod
    def _fallback_answer(context: Dict[str, Any]) -> str:
        """LLM 不可用時的模板 fallback。"""
        has_policy = context.get("has_policy", False)

        if has_policy:
            policy_content = context["company_policy_raw"]["content"][:500]
            return f"""📋 **知識庫相關內容**：
{policy_content}

💡 **提醒**：以上為知識庫中最相關的段落，AI 生成回答目前暫時無法使用。"""

        else:
            return "抱歉，目前知識庫中的資料不足以回答此問題。請嘗試換個方式提問，或向管理員確認是否需要補充相關文件。"

    def format_summary(self, result: Dict[str, Any]) -> str:
        """格式化摘要（用於顯示）"""
        summary = f"**問題**：{result['question']}\n\n"
        summary += result["answer"]

        if result.get("sources"):
            summary += "\n\n**參考來源**：\n"
            for source in result["sources"]:
                title = source.get("title") or source.get("filename") or ""
                score = source.get("score")
                if score is not None:
                    summary += f"- 📄 {title} (相關度: {score:.2f})\n"
                else:
                    summary += f"- 📄 {title}\n"

        summary += f"\n\n{result['disclaimer']}"
        return summary
