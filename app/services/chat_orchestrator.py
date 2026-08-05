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
8. 使用繁體中文回答
9. 參考資料以【檔名】開頭的片段，其後第一行通常是該文件的標題或表頭；使用者指定特定文件時，應根據該文件片段的實際內容推論作答，不要僅因文件中沒有與問題完全同名的欄位就拒答"""

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
        """純檢索：經 MultiStepOrchestrator（計劃→多臂→合成）組裝上下文。"""
        request_id = str(uuid.uuid4())

        if authz is None:
            return self._build_context(
                question=question,
                company_policy={"status": "error", "error": "authz_required", "results": []},
                request_id=request_id,
            )

        from app.services.multi_step_orchestrator import MultiStepOrchestrator

        try:
            orch_result = await MultiStepOrchestrator().run(
                authz=authz,
                question=question,
                top_k=top_k,
                use_gateway=use_gateway,
            )
        except Exception as exc:
            logger.warning("multi-step orchestration failed: %s", exc)
            orch_result = {
                "status": "error",
                "error": str(exc),
                "results": [],
                "catalog_hits": [],
                "clause_projections": [],
                "query_plan": {},
                "providers_called": [],
                "degraded": True,
                "retrieval_mode": "error",
                "has_evidence": False,
            }

        company_policy_result: Dict[str, Any] = {
            "status": "success" if orch_result.get("has_evidence") else "empty",
            "results": list(orch_result.get("results") or []),
            "catalog_hits": list(orch_result.get("catalog_hits") or []),
            "clause_projections": list(orch_result.get("clause_projections") or []),
            "query_plan": orch_result.get("query_plan") or {},
            "providers_called": list(orch_result.get("providers_called") or []),
            "fusion_policy_version": orch_result.get("fusion_policy_version") or "",
            "query_domain": orch_result.get("query_domain") or "",
            "dropped_non_citable": orch_result.get("dropped_non_citable") or 0,
            "degraded": bool(orch_result.get("degraded")),
            "retrieval_mode": orch_result.get("retrieval_mode") or "multi_step",
            "trace": orch_result.get("trace") or {},
            "refusal": orch_result.get("refusal"),
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
        catalog_hits = company_policy.get("catalog_hits") or []
        # 盤點題即使 chunk 臂無命中，catalog 命中也算有證據可答
        if catalog_hits and not has_policy:
            has_policy = True

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
                # ADR-009 融合觀測（FD-FUSION 閘門斷言欄位）
                "fusion_policy_version": company_policy.get("fusion_policy_version") or "",
                "query_domain": company_policy.get("query_domain") or "",
                "dropped_non_citable": company_policy.get("dropped_non_citable") or 0,
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

        # 檔名鎖定（《檔名》）查詢：證據集中在單一文件，放寬上下文段數上限，
        # 避免長文件的目標章節被固定 5 段截掉（2026-08-03 盲測 B02/B07/B13 根因）
        _qp = company_policy.get("query_plan") or {}
        _max_ctx = 12 if _qp.get("mentioned_documents") else 5
        top_results = (company_policy.get("results") or [])[:_max_ctx]
        if top_results:
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

        # ADR-008：catalog 臂命中進 context（檔名清單）與 sources（可引用）
        if catalog_hits:
            filenames = [h["filename"] for h in catalog_hits if h.get("filename")]
            listing = "\n".join(f"{i}. {fn}" for i, fn in enumerate(filenames, 1))
            context["context_parts"].insert(
                0,
                f"【庫內文件清單】（文件層檢索，共 {len(filenames)} 份符合；"
                "回答盤點問題時以此清單為準，不得虛構未列出的檔名）\n" + listing,
            )
            for h in catalog_hits[:10]:
                context["sources"].insert(0, {
                    "type": "catalog",
                    "title": h["filename"],
                    "snippet": (h.get("content") or "")[:200],
                    "score": h.get("score") or 0,
                    "document_id": h.get("document_id"),
                    "provider": "enclave",
                    "granularity": "catalog",
                    "accessible": True,
                })
        qp = company_policy.get("query_plan") or {}
        context["retrieval"]["arms"] = list(
            qp.get("arms") or (["catalog", "chunk"] if catalog_hits else ["chunk"])
        )
        if qp:
            context["retrieval"]["query_plan"] = {
                "plan_version": qp.get("plan_version") or "",
                "intent": qp.get("intent") or "",
                "arms": list(qp.get("arms") or []),
                "sub_queries": list(qp.get("sub_queries") or []),
                "domain": qp.get("domain") or "",
            }

        projections = company_policy.get("clause_projections") or []
        if projections:
            from app.services.clause_projection import format_projection_context
            context["context_parts"].insert(0, format_projection_context(projections))
            context["retrieval"]["clause_projections"] = len(projections)
            if not context["has_policy"]:
                context["has_policy"] = True
                context["retrieval"]["label"] = "已搜尋可存取知識"
            for p in projections:
                context["sources"].insert(0, {
                    "type": "clause_projection",
                    "title": p.get("filename") or "條款對照投影",
                    "snippet": f"{len(p.get('clauses') or [])} 條條款對照",
                    "score": 1.0,
                    "document_id": p.get("document_id"),
                    "provider": "enclave",
                    "granularity": "compiled",
                    "accessible": True,
                })

        # VISION Phase 2：逐步 trace + 解釋式拒答
        if company_policy.get("trace"):
            context["retrieval"]["trace"] = company_policy["trace"]
        refusal = company_policy.get("refusal")
        intent = (qp or {}).get("intent") or ""
        if intent == "unanswerable":
            context["has_policy"] = False
            context["retrieval"]["label"] = "題目超出知識庫範圍，拒絕臆測"
        if refusal:
            context["retrieval"]["refusal"] = refusal
            context["refusal"] = refusal
            if not context["has_policy"]:
                context["retrieval"]["label"] = "知識不足，已準備解釋式拒答"

        return context

    async def stream_answer(
        self,
        question: str,
        context: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
        include_followup: bool = True,
    ) -> AsyncGenerator[str, None]:
        """
        串流生成 LLM 回答（SSE 用），含逐字溯源稽核層（SOURCE_VERIFY_MODE）。

        - off：現行行為，逐 token 輸出。
        - shadow：照常逐 token 輸出；串流結束後稽核，結果記 log 並存入
          ``context["source_verification"]``，不影響使用者。
        - enforce：先緩衝完整回答再稽核，通過才輸出；失敗則以約束式 prompt
          重新生成一次，再失敗則輸出「僅含已驗證重點」的誠實回答。
        """
        if not self._openai_async or not context["has_policy"]:
            yield self._fallback_answer(context)
            return
        # 有結構化拒答且意圖為不可答 → 強制拒答，不讓 LLM 胡謅
        refusal = context.get("refusal") or (context.get("retrieval") or {}).get("refusal")
        if refusal and (context.get("retrieval") or {}).get("query_plan", {}).get("intent") == "unanswerable":
            yield refusal.get("message") or self._fallback_answer(context)
            return

        mode = str(getattr(settings, "SOURCE_VERIFY_MODE", "off") or "off").lower()

        if mode == "enforce":
            async for chunk in self._stream_answer_enforce(
                question, context, history, include_followup
            ):
                yield chunk
            return

        if mode == "shadow":
            buffered: List[str] = []
            async for chunk in self._stream_answer_raw(
                question, context, history, include_followup
            ):
                buffered.append(chunk)
                yield chunk
            result = await self._run_source_verification(
                question, "".join(buffered), context, mode="shadow"
            )
            if result is not None:
                context["source_verification"] = result.to_dict()
                logger.info(
                    "source_verify[shadow] verified=%s claims=%d unsupported=%d reason=%s detail=%s",
                    result.verified, result.total_claims,
                    len(result.unsupported_claims), result.reason,
                    result.unsupported_claims[:5] if result.unsupported_claims else "",
                )
            return

        async for chunk in self._stream_answer_raw(
            question, context, history, include_followup
        ):
            yield chunk

    async def _stream_answer_raw(
        self,
        question: str,
        context: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
        include_followup: bool = True,
        extra_system_note: str = "",
    ) -> AsyncGenerator[str, None]:
        """逐 token 串流生成（不含稽核）。``extra_system_note`` 供約束式重生成注入。"""
        messages = self._build_llm_messages(
            question, context, history=history, include_followup=include_followup
        )
        if extra_system_note:
            messages[0]["content"] += "\n\n" + extra_system_note

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

    async def _run_source_verification(
        self,
        question: str,
        answer: str,
        context: Dict[str, Any],
        *,
        mode: str,
    ):
        """呼叫逐字溯源稽核；任何失敗都回傳 None 或未通過結果，絕不拋例外。"""
        try:
            from app.services.source_verifier import verify_answer

            client = self._openai_async
            model = self._llm_model
            use_internal = False
            if getattr(settings, "SOURCE_VERIFY_USE_INTERNAL_LLM", True) and self._internal_async:
                client = self._internal_async
                model = self._internal_model
                use_internal = True
            override = str(getattr(settings, "SOURCE_VERIFY_MODEL", "") or "").strip()
            if override:
                model = override
            return await verify_answer(
                question,
                answer,
                context.get("context_parts") or [],
                client,
                model,
                mode=mode,
                disable_thinking=use_internal,
            )
        except Exception as e:
            logger.warning("source_verify: verification crashed, treating as unverified: %s", e)
            return None

    async def _stream_answer_enforce(
        self,
        question: str,
        context: Dict[str, Any],
        history: Optional[List[Dict[str, str]]],
        include_followup: bool,
    ) -> AsyncGenerator[str, None]:
        """enforce 模式：緩衝 → 稽核 → 通過才輸出；失敗則約束式重生成一次。"""
        buffered: List[str] = []
        async for chunk in self._stream_answer_raw(
            question, context, history, include_followup
        ):
            buffered.append(chunk)
        answer = "".join(buffered)

        result = await self._run_source_verification(question, answer, context, mode="enforce")
        if result is not None:
            context["source_verification"] = result.to_dict()
            logger.info(
                "source_verify[enforce] first_pass verified=%s claims=%d unsupported=%d reason=%s",
                result.verified, result.total_claims,
                len(result.unsupported_claims), result.reason,
            )
        if result is not None and result.verified:
            yield answer
            return

        # 第一次未通過（或稽核不可用）→ 約束式重生成一次
        unsupported_note = ""
        if result is not None and result.unsupported_claims:
            unsupported_note = "、".join(result.unsupported_claims[:5])
        strict_note = (
            "【稽核要求】前一版回答含有無法從參考資料逐字驗證的內容"
            + (f"（{unsupported_note}）。" if unsupported_note else "。")
            + "請重新回答，只使用參考資料中逐字存在的資訊；"
            "若參考資料不足以回答，直接說明無法回答，不要推測。"
        )
        regenerated: List[str] = []
        async for chunk in self._stream_answer_raw(
            question, context, history, include_followup, extra_system_note=strict_note
        ):
            regenerated.append(chunk)
        regen_answer = "".join(regenerated)

        regen_result = await self._run_source_verification(
            question, regen_answer, context, mode="enforce"
        )
        if regen_result is not None:
            context["source_verification"] = regen_result.to_dict()
            logger.info(
                "source_verify[enforce] regen verified=%s claims=%d unsupported=%d reason=%s",
                regen_result.verified, regen_result.total_claims,
                len(regen_result.unsupported_claims), regen_result.reason,
            )
        if regen_result is not None and regen_result.verified:
            yield regen_answer
            return

        # 兩次都無法完全溯源 → 誠實輸出：僅給已驗證重點，其餘明說無法確認
        verified_points = (regen_result or result)
        if verified_points is not None and verified_points.verified_claims:
            lines = [
                "目前無法產生每一句都能對回文件原文的完整回答。為避免誤導，"
                "以下僅列出已在文件中逐字確認的重點：",
                "",
            ]
            for c in verified_points.verified_claims[:5]:
                lines.append(f"- {c['claim']}")
            lines.append("")
            lines.append("其餘細節未能在文件中找到逐字依據，建議查閱原文或補充文件後再問。")
            yield "\n".join(lines)
        else:
            yield (
                "目前知識庫的檢索內容不足以產生可逐字溯源的回答，"
                "為避免提供無法驗證的資訊，此題暫不作答。"
                "建議縮小問題範圍，或確認相關文件已完整上傳。"
            )
        logger.warning(
            "source_verify[enforce] refused: reason=%s",
            (regen_result or result).reason if (regen_result or result) else "verifier_unavailable",
        )

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
        """LLM 不可用或無證據時的模板；優先使用解釋式拒答。"""
        refusal = context.get("refusal") or (context.get("retrieval") or {}).get("refusal")
        if refusal and refusal.get("message"):
            return refusal["message"]

        has_policy = context.get("has_policy", False)
        if has_policy:
            raw = context.get("company_policy_raw") or {}
            policy_content = (raw.get("content") or "")[:500]
            return f"""📋 **知識庫相關內容**：
{policy_content}

💡 **提醒**：以上為知識庫中最相關的段落，AI 生成回答目前暫時無法使用。"""

        return (
            "抱歉，目前知識庫中的資料不足以回答此問題。"
            "請嘗試換個方式提問，或向管理員確認是否需要補充相關文件。"
        )

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
