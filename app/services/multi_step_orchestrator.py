"""VISION Phase 2 — MultiStepOrchestrator：計劃→多臂→合成。

把 chat 從「單次 retrieve」改為依 QueryPlan 逐步執行臂並留下 trace。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.gateway.contracts import SearchDomain
from app.services.query_plan import QueryPlan, _DOCISH, build_query_plan
from app.services.refusal import (
    amount_question_lacks_numeric_evidence,
    build_refusal,
    guarantee_question_lacks_evidence,
)
from app.services.tool_router import arms_for_plan, queries_for_arm
from app.services.trace_recorder import RetrievalTraceView

logger = logging.getLogger(__name__)


class MultiStepOrchestrator:
    """執行 QueryPlan 的多步檢索編排。"""

    async def run(
        self,
        *,
        authz,
        question: str,
        top_k: int = 5,
        use_gateway: bool = True,
        plan: Optional[QueryPlan] = None,
        db=None,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.retrieval_facade import get_retrieval_facade

        facade = get_retrieval_facade()
        from app.services.kb_scope_policy import resolve_kb_revision_scope

        self._filter_dict = resolve_kb_revision_scope(
            authz=authz, requested=filter_dict, db=db
        )
        plan = plan or build_query_plan(question)
        arms = arms_for_plan(plan)
        plan.arms = list(arms)
        # unanswerable 仍做一次輕量 chunk 確認，避免假拒答
        if plan.intent == "unanswerable" and "chunk" not in arms:
            arms = ["chunk"]
        # 客戶／檔名 CJK token：先跑 catalog 再 scoped，避免純語意廣搜撈到同類型雜檔
        # （Blind Z4-028「金正昌報價提案」）
        # 前置條件：token 必須實際命中 catalog 檔名索引，避免一般問答誤掛盤點臂
        if "catalog" not in arms:
            from app.services.catalog_retrieval import _filename_tokens

            tokens = [t for t in _filename_tokens(question) if len(t) >= 3]
            if tokens and self._catalog_index_hit(authz, tokens, db):
                arms = ["catalog"] + list(arms)
        # 跨語條款文件：即使非 translate 意圖也掛 compiled 臂讀投影
        ql = (question or "").casefold()
        if (
            any(k in ql for k in ("eti", "base code", "緬甸", "burmese"))
            and "compiled" not in arms
        ):
            arms = list(arms) + ["compiled"]

        trace = RetrievalTraceView(
            plan_version=plan.plan_version,
            intent=plan.intent,
        )
        chunk_results: List[Dict[str, Any]] = []
        catalog_hits: List[Dict[str, Any]] = []
        clause_projections: List[Dict[str, Any]] = []
        providers_called: List[str] = []
        fusion_meta = {
            "fusion_policy_version": "",
            "query_domain": plan.domain,
            "dropped_non_citable": 0,
            "degraded": False,
            "retrieval_mode": "multi_step",
        }

        for arm in arms:
            queries = queries_for_arm(plan, arm, question)
            if arm == "catalog":
                await self._run_catalog(
                    facade, authz, queries, catalog_hits, trace, db=db
                )
            elif arm == "chunk":
                meta = await self._run_chunk(
                    facade,
                    authz,
                    queries,
                    chunk_results,
                    trace,
                    top_k=top_k,
                    use_gateway=use_gateway,
                    plan=plan,
                    question=question,
                    catalog_hits=catalog_hits,
                    db=db,
                )
                for p in meta.get("providers_called") or []:
                    if p not in providers_called:
                        providers_called.append(p)
                fusion_meta.update(
                    {k: v for k, v in meta.items() if k != "providers_called"}
                )
            elif arm == "compiled":
                await self._run_compiled(
                    authz, question, clause_projections, trace, db=db
                )
            elif arm == "pageindex":
                # P2-4：PageIndex 長文件臂（feature-flagged）
                await self._run_pageindex(authz, question, chunk_results, trace, db=db)
            elif arm in {"structured", "procedure"}:
                await self._run_projection(
                    arm, authz, question, plan, chunk_results, trace, db=db
                )

        refusal = None
        has_evidence = bool(chunk_results or catalog_hits or clause_projections)
        missing_named = list(fusion_meta.pop("missing_named_documents", None) or [])
        if missing_named:
            refusal = build_refusal(
                question=question,
                plan_intent="unanswerable",
                chunk_hits=chunk_results,
                catalog_hits=catalog_hits,
                clause_projections=clause_projections,
            )
            refusal["reason"] = "named_file_missing"
            refusal["missing_docs"] = missing_named
            refusal["message"] = (
                "抱歉，目前無法依據知識庫中的資料回答此問題。\n"
                "題目指定的文件未能在庫內取到可用內容，系統拒絕改用其他文件臆測：\n"
                + "\n".join(f"- {n}" for n in missing_named[:8])
                + "\n請確認該檔已完成入庫，或改問庫內已有文件可直接摘錄的事實。"
            )
            has_evidence = False
            trace.refusal = refusal
        elif has_evidence and amount_question_lacks_numeric_evidence(
            question, chunk_results
        ):
            # 已命中檔名／文件時，金額常在非 top-k chunk（表尾總價）→ 先擴文件頭再判定
            chunk_results = await self._expand_chunks_for_amount(
                facade, authz, chunk_results, catalog_hits, db=db
            )
            if amount_question_lacks_numeric_evidence(question, chunk_results):
                refusal = build_refusal(
                    question=question,
                    plan_intent=plan.intent,
                    chunk_hits=chunk_results,
                    catalog_hits=catalog_hits,
                    clause_projections=clause_projections,
                )
                has_evidence = False
                trace.refusal = refusal
            else:
                trace.add_step(
                    arm="amount_expand",
                    query=question[:80],
                    hit_count=len(chunk_results),
                    hit_titles=list(
                        {
                            (h.get("filename") or "")
                            for h in chunk_results
                            if h.get("filename")
                        }
                    )[:8],
                )
        elif has_evidence and guarantee_question_lacks_evidence(
            question, chunk_results
        ):
            refusal = build_refusal(
                question=question,
                plan_intent=plan.intent,
                chunk_hits=chunk_results,
                catalog_hits=catalog_hits,
                clause_projections=clause_projections,
            )
            refusal["reason"] = "guarantee_not_in_evidence"
            refusal["message"] = (
                "抱歉，目前無法依據知識庫中的資料回答此問題。\n"
                "題目要求「保證」事項，但已召回內容未出現對應保證條款，系統拒絕推論或頂替。"
            )
            has_evidence = False
            trace.refusal = refusal
        elif not has_evidence or plan.intent == "unanswerable":
            refusal = build_refusal(
                question=question,
                plan_intent=plan.intent,
                chunk_hits=chunk_results,
                catalog_hits=catalog_hits,
                clause_projections=clause_projections,
            )
            # unanswerable：即使有雜訊命中也拒答
            if plan.intent == "unanswerable":
                has_evidence = False
            elif not has_evidence:
                pass
            trace.refusal = refusal

        return {
            "status": "success" if has_evidence else "empty",
            "results": chunk_results[: max(top_k * 3, 16)],
            "catalog_hits": catalog_hits,
            "clause_projections": clause_projections,
            "query_plan": plan.to_dict(),
            "providers_called": providers_called or ["document"],
            "trace": trace.to_dict(),
            "refusal": refusal,
            "has_evidence": has_evidence,
            **fusion_meta,
        }

    async def _run_projection(
        self, arm, authz, question, plan, out, trace, *, db=None
    ) -> None:
        from app.db.session import SessionLocal
        from app.services.projection_retrieval import (
            load_procedure_evidence,
            load_structured_evidence,
        )

        session = db or SessionLocal()
        try:
            from app.services.rls import apply_rls_context

            apply_rls_context(session, authz.tenant_id)
            loader = (
                load_structured_evidence
                if arm == "structured"
                else load_procedure_evidence
            )
            rows = loader(
                db=session,
                authz=authz,
                question=question,
                plan=plan,
                scope=getattr(self, "_filter_dict", None) or {},
            )
            out[0:0] = rows
            trace.add_step(
                arm=arm,
                query=question,
                hit_count=len(rows),
                hit_titles=[row.get("filename") or arm for row in rows],
            )
        except Exception as exc:
            logger.warning("%s projection step failed: %s", arm, exc)
            trace.add_step(arm=arm, query=question, hit_count=0, error=str(exc))
        finally:
            if db is None:
                session.close()

    async def _expand_chunks_for_amount(
        self,
        facade,
        authz,
        chunk_results: List[Dict[str, Any]],
        catalog_hits: List[Dict[str, Any]],
        *,
        n: int = 8,
        db=None,
    ) -> List[Dict[str, Any]]:
        """金額題：對已命中檔名補文件前段 chunks，避免總價在尾段被拒答誤殺。"""
        filenames: List[str] = []
        for h in chunk_results:
            fn = h.get("filename") or (h.get("metadata") or {}).get("filename")
            if fn and fn not in filenames:
                filenames.append(fn)
        for h in catalog_hits:
            fn = (
                h.get("filename")
                if isinstance(h, dict)
                else getattr(h, "filename", None)
            )
            if fn and fn not in filenames:
                filenames.append(fn)
        if not filenames:
            return chunk_results

        loop = asyncio.get_event_loop()
        seen = {
            (r.get("id") or f"{r.get('document_id')}:{r.get('chunk_index')}")
            for r in chunk_results
        }
        out = list(chunk_results)
        for fn in filenames[:6]:
            try:
                head = await loop.run_in_executor(
                    None,
                    lambda f=fn: facade.get_document_head(
                        authz=authz,
                        filename=f,
                        n=n,
                        scope=getattr(self, "_filter_dict", None),
                        db=db,
                    ),
                )
            except Exception as exc:
                logger.warning("amount expand head failed for %s: %s", fn, exc)
                continue
            for h in head:
                key = h.get("id") or f"{h.get('document_id')}:{h.get('chunk_index')}"
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "id": h.get("id"),
                        "content": h.get("content") or "",
                        "score": h.get("score"),
                        "document_id": h.get("document_id"),
                        "filename": fn,
                        "chunk_index": h.get("chunk_index"),
                        "source": "amount_expand_head",
                        "citations": [],
                    }
                )
        return out

    def _catalog_index_hit(self, authz, tokens: List[str], db) -> bool:
        """檔名 token 實際命中 catalog 索引才掛 catalog 臂；任何失敗一律不掛。"""
        try:
            from app.services.catalog_retrieval import get_catalog_retriever

            tenant_id = getattr(authz, "tenant_id", None)
            if tenant_id is None:
                return False
            scope = getattr(self, "_filter_dict", None) or {}
            revision_ids = [
                UUID(str(value)) for value in (scope.get("kb_revision_ids") or [])
            ]
            return get_catalog_retriever().filename_token_hit(
                tenant_id=tenant_id,
                tokens=tokens,
                kb_revision_id=scope.get("kb_revision_id"),
                kb_revision_ids=revision_ids if "kb_revision_ids" in scope else None,
                authz=authz,
                db=db,
            )
        except Exception as exc:
            logger.debug("catalog index pre-check skipped: %s", exc)
            return False

    async def _run_catalog(
        self, facade, authz, queries, out, trace, *, db=None
    ) -> None:
        seen = set()
        loop = asyncio.get_event_loop()
        for q in queries:
            try:
                hits = await loop.run_in_executor(
                    None,
                    lambda qq=q: facade.search_catalog(
                        authz=authz,
                        query=qq,
                        filters=getattr(self, "_filter_dict", None),
                        db=db,
                    ),
                )
                titles = []
                for h in hits:
                    hid = h.document_id or h.filename
                    if hid in seen:
                        continue
                    seen.add(hid)
                    row = h.to_dict()
                    out.append(row)
                    if h.filename:
                        titles.append(h.filename)
                trace.add_step(
                    arm="catalog", query=q, hit_count=len(titles), hit_titles=titles
                )
            except Exception as exc:
                logger.warning("catalog step failed: %s", exc)
                trace.add_step(arm="catalog", query=q, hit_count=0, error=str(exc))

    async def _run_chunk(
        self,
        facade,
        authz,
        queries,
        out,
        trace,
        *,
        top_k,
        use_gateway,
        plan=None,
        question: str = "",
        catalog_hits: Optional[List[Dict[str, Any]]] = None,
        db=None,
    ) -> Dict[str, Any]:
        meta = {
            "providers_called": [],
            "fusion_policy_version": "",
            "query_domain": "",
            "dropped_non_citable": 0,
            "degraded": False,
            "retrieval_mode": "gateway",
        }
        seen = set()
        mentioned = list(getattr(plan, "mentioned_documents", None) or [])
        # 比價子查詢常是文件標題（無《》），一併納入 scoped 檔名臂
        for sq in list(getattr(plan, "sub_queries", None) or []):
            sq = (sq or "").strip()
            if sq and sq not in mentioned and _DOCISH.search(sq):
                mentioned.append(sq)
        # Catalog 錨定：題目 token 命中 catalog 檔名時，強制 scoped，避免語意廣搜撈到同類型雜檔
        # （Blind Z4-028「金正昌報價提案」→ 誤召 CYS／味特提案）
        if not mentioned and catalog_hits:
            from app.services.catalog_retrieval import _filename_tokens

            toks = [t for t in _filename_tokens(question) if len(t) >= 2]
            for h in catalog_hits:
                fn = (
                    h.get("filename")
                    if isinstance(h, dict)
                    else getattr(h, "filename", None)
                )
                if not fn:
                    continue
                fn_l = fn.casefold()
                if any(t in fn or t.casefold() in fn_l for t in toks):
                    if fn not in mentioned:
                        mentioned.append(fn)
            if mentioned:
                trace.add_step(
                    arm="catalog_anchor",
                    query=question[:80],
                    hit_count=len(mentioned),
                    hit_titles=list(mentioned)[:8],
                )
        scoped_ok = False
        missing_named: List[str] = []
        if mentioned:
            before = len(out)
            await self._run_scoped_chunk(
                facade,
                authz,
                mentioned,
                question or (queries[0] if queries else ""),
                out,
                trace,
                top_k=top_k,
                seen=seen,
                db=db,
            )
            hit_names = {r.get("filename") for r in out[before:] if r.get("filename")}
            # soft：子查詢標題只要被某命中檔名包含，即算取到
            still_missing = []
            for fn in mentioned:
                if fn in hit_names:
                    continue
                if any(fn in (h or "") or (h or "") in fn for h in hit_names):
                    continue
                still_missing.append(fn)
            missing_named = still_missing
            scoped_ok = len(out) > before and not missing_named
            # 比價：只要取到至少兩邊證據就略過廣搜，避免雜訊
            if (
                not scoped_ok
                and getattr(plan, "intent", "") == "compare"
                and len(hit_names) >= 2
                and len(out) > before
            ):
                scoped_ok = True
                missing_named = []
            if missing_named:
                meta["missing_named_documents"] = missing_named
            elif scoped_ok or len(out) > before:
                # 金額題：把含報價數字的段落提前，避免成效／ROAS 雜訊佔滿上下文（Z4-009）
                q = question or ""
                if any(
                    a in q
                    for a in (
                        "金額",
                        "總價",
                        "報價",
                        "價位",
                        "價格",
                        "多少錢",
                        "費用",
                        "月費",
                    )
                ):
                    from app.services.refusal import _AMOUNT_IN_TEXT

                    priced = []
                    rest = []
                    for r in out:
                        blob = r.get("content") or ""
                        if _AMOUNT_IN_TEXT.search(blob) and any(
                            k in blob
                            for k in (
                                "報價",
                                "月費",
                                "總計",
                                "未稅",
                                "含稅",
                                "金額",
                                "NT$",
                                "元",
                                "電商方案",
                            )
                        ):
                            priced.append(r)
                        else:
                            rest.append(r)
                    if priced:
                        out[:] = priced + rest
            trace.add_step(
                arm="chunk",
                query=(
                    "(skipped: filename-scoped hits sufficient)"
                    if (scoped_ok or len(out) > before) and not missing_named
                    else "(named scope attempted)"
                ),
                hit_count=len(out) - before,
            )
            return meta
        # 題目點名檔案但 scoped 未取到 → 禁止他檔廣搜頂替（Blind Z3-035）
        if mentioned and missing_named:
            meta["missing_named_documents"] = missing_named
            trace.add_step(
                arm="chunk",
                query="(skipped: named file missing — no cross-file substitute)",
                hit_count=0,
                hit_titles=missing_named,
            )
            return meta
        for q in queries:
            try:
                scope = getattr(self, "_filter_dict", None) or None
                if use_gateway:
                    retrieved = await facade.search_gateway(
                        authz=authz,
                        query=q,
                        top_k=top_k,
                        domain=SearchDomain.HYBRID,
                        db=db,
                        scope=scope,
                    )
                else:
                    loop = asyncio.get_event_loop()
                    retrieved = await loop.run_in_executor(
                        None,
                        lambda qq=q: facade.search(
                            authz=authz, query=qq, top_k=top_k, db=db, scope=scope
                        ),
                    )
                titles = []
                all_citations = list(retrieved.citations or [])
                for i, r in enumerate(retrieved.results or []):
                    key = r.get("id") or f"{r.get('document_id')}:{i}"
                    if key in seen:
                        continue
                    seen.add(key)
                    c = all_citations[i] if i < len(all_citations) else None
                    filename = (
                        (r.get("metadata") or {}).get("filename", "")
                        or r.get("filename")
                        or ""
                    )
                    row = {
                        "id": r.get("id"),
                        "content": r.get("content") or r.get("text") or "",
                        "score": r.get("score"),
                        "document_id": r.get("document_id"),
                        "filename": filename,
                        "chunk_index": (r.get("metadata") or {}).get("chunk_index"),
                        "source": r.get("provider"),
                        "metadata": dict(r.get("metadata") or {}),
                        "citations": (
                            [
                                {
                                    "citation_id": c.citation_id,
                                    "document_id": str(c.canonical_document_id),
                                    "canonical_resource_type": c.canonical_resource_type,
                                    "canonical_resource_id": c.canonical_resource_id,
                                    "document_revision": c.document_revision,
                                    "provider": c.provider,
                                    "page": c.page,
                                    "bbox": c.bbox,
                                    "section": c.section,
                                    "section_path": c.section_path,
                                    "paragraph_index": c.paragraph_index,
                                    "slide_number": c.slide_number,
                                    "worksheet": c.worksheet,
                                    "table_name": c.table_name,
                                    "row_number": c.row_number,
                                    "column_name": c.column_name,
                                    "cell_range": c.cell_range,
                                    "start_ms": c.start_ms,
                                    "end_ms": c.end_ms,
                                    "speaker": c.speaker,
                                    "frame_index": c.frame_index,
                                    "evidence_url": c.evidence_url,
                                }
                            ]
                            if c is not None
                            else []
                        ),
                    }
                    out.append(row)
                    if filename:
                        titles.append(filename)
                audit = getattr(retrieved, "audit_trail", None)
                if audit:
                    for p in getattr(audit, "providers_called", None) or []:
                        if p not in meta["providers_called"]:
                            meta["providers_called"].append(p)
                    meta["fusion_policy_version"] = (
                        getattr(audit, "fusion_policy_version", "")
                        or meta["fusion_policy_version"]
                    )
                    meta["query_domain"] = (
                        getattr(audit, "query_domain", "") or meta["query_domain"]
                    )
                    meta["dropped_non_citable"] = (
                        getattr(audit, "dropped_non_citable", 0) or 0
                    ) + int(meta.get("dropped_non_citable") or 0)
                gw_status = getattr(retrieved, "gateway_status", None)
                if gw_status == "partial":
                    meta["degraded"] = True
                trace.add_step(
                    arm="chunk", query=q, hit_count=len(titles), hit_titles=titles
                )
            except Exception as exc:
                logger.warning("chunk step failed: %s", exc)
                meta["degraded"] = True
                meta["retrieval_mode"] = "canonical_fallback"
                try:
                    loop = asyncio.get_event_loop()
                    retrieved = await loop.run_in_executor(
                        None,
                        lambda qq=q: facade.search(
                            authz=authz, query=qq, top_k=top_k, db=db, scope=scope
                        ),
                    )
                    titles = []
                    for r in retrieved.results or []:
                        filename = r.get("filename") or ""
                        out.append(
                            dict(r)
                            if isinstance(r, dict)
                            else {
                                "content": getattr(r, "content", ""),
                                "document_id": getattr(r, "document_id", None),
                                "score": getattr(r, "score", 0),
                                "filename": filename,
                            }
                        )
                        if filename:
                            titles.append(filename)
                    meta["providers_called"] = ["document"]
                    trace.add_step(
                        arm="chunk",
                        query=q,
                        hit_count=len(titles),
                        hit_titles=titles,
                        error=str(exc),
                    )
                except Exception as exc2:
                    trace.add_step(
                        arm="chunk",
                        query=q,
                        hit_count=0,
                        error=f"{exc}; fallback={exc2}",
                    )
        return meta

    async def _run_scoped_chunk(
        self, facade, authz, filenames, query, out, trace, *, top_k, seen, db=None
    ) -> None:
        """檔名導向檢索：《檔名》提及時直接以 metadata filename scope 取證。

        全域語意檢索對「009_DOC003~3.pdf」這類檔名訊號很弱，會被其他
        文件的語意相似 chunk 擠掉；明確提及檔名時必須把該檔 chunk 置前。

        查詢會先移除《檔名》片段——檔名約束已由 scope filter 表達，留在
        query 裡只會稀釋 embedding 語意訊號（2026-08-03 盲測 B23 根因）。
        scoped 情境已限定單一文件、無跨檔雜訊風險，故提高 top_k 以提升
        長文件內目標章節的命中率（2026-08-03 盲測 B13/B23 根因）。
        """
        from app.services.query_plan import _DOC_MENTION, _DOC_MENTION_QUOTED

        clean_query = _DOC_MENTION.sub("", query)
        clean_query = _DOC_MENTION_QUOTED.sub("", clean_query).strip() or query
        scoped_k = max(top_k * 2, 12)
        loop = asyncio.get_event_loop()
        for fn in filenames:
            try:
                import unicodedata as _ud

                resolved_fn = fn
                base_scope = dict(getattr(self, "_filter_dict", None) or {})
                # 先嘗試以提及字串直接 scope；失敗再用檔名包含／尾碼軟匹配解析真實檔名
                retrieved = await loop.run_in_executor(
                    None,
                    lambda f=fn: facade.search(
                        authz=authz,
                        query=clean_query,
                        top_k=scoped_k,
                        # hybrid：scoped 內仍需 BM25 關鍵字訊號，否則
                        # 「單價/MOQ」這類詞在純語意下贏不了產品概述 chunk
                        # （2026-08-06 線上報價問答根因）
                        mode="hybrid",
                        scope={**base_scope, "filename": f},
                        db=db,
                    ),
                )
                hits = [
                    r
                    for r in (retrieved.results or [])
                    if (
                        (r.get("metadata") or {}).get("filename")
                        or r.get("filename")
                        or ""
                    )
                    == fn
                ]
                if not hits:
                    want = _ud.normalize("NFKC", fn).casefold().replace(" ", "")
                    # 用檔名本身當 query 拉候選，再軟匹配（避免語意 query 擠掉目標檔）
                    broad = await loop.run_in_executor(
                        None,
                        lambda: facade.search(
                            authz=authz,
                            query=fn,
                            top_k=max(top_k * 4, 20),
                            scope=base_scope,
                            db=db,
                        ),
                    )
                    matched_name = None
                    for r in broad.results or []:
                        cand = (
                            (r.get("metadata") or {}).get("filename")
                            or r.get("filename")
                            or ""
                        )
                        cand_n = _ud.normalize("NFKC", cand).casefold().replace(" ", "")
                        if not cand_n:
                            continue
                        matched = want in cand_n or cand_n in want
                        if not matched and len(want) >= 4:
                            for suf_len in (8, 6, 4):
                                if len(want) < suf_len:
                                    continue
                                suf = want[-suf_len:]
                                if suf in {
                                    "股份有限公司",
                                    "有限公司",
                                    "企業社",
                                    "工作室",
                                }:
                                    continue
                                if not any(
                                    k in suf
                                    for k in (
                                        "報價",
                                        "設計",
                                        "提案",
                                        "合約",
                                        "契約",
                                        "企劃",
                                        "委任",
                                    )
                                ):
                                    continue
                                if suf in cand_n:
                                    matched = True
                                    break
                        if matched:
                            matched_name = cand
                            break
                    if matched_name:
                        resolved_fn = matched_name
                        retrieved = await loop.run_in_executor(
                            None,
                            lambda f=matched_name: facade.search(
                                authz=authz,
                                query=clean_query,
                                top_k=scoped_k,
                                mode="semantic",
                                scope={**base_scope, "filename": f},
                                db=db,
                            ),
                        )
                        hits = [
                            r
                            for r in (retrieved.results or [])
                            if (
                                (r.get("metadata") or {}).get("filename")
                                or r.get("filename")
                                or ""
                            )
                            == matched_name
                        ]
                        if not hits:
                            # scope 仍空時，至少收下檔名命中的 broad 列
                            hits = [
                                r
                                for r in (broad.results or [])
                                if (
                                    (r.get("metadata") or {}).get("filename")
                                    or r.get("filename")
                                    or ""
                                )
                                == matched_name
                            ]
                # 文件頭部（chunk 0..1）恆常附上：標題/表頭/基本資料固定在
                # 文件開頭，語意排名不一定進 top-k（2026-08-03 E073 根因）
                head = await loop.run_in_executor(
                    None,
                    lambda f=resolved_fn: facade.get_document_head(
                        authz=authz,
                        filename=f,
                        n=2,
                        scope=getattr(self, "_filter_dict", None),
                        db=db,
                    ),
                )
                head_new = []
                for h in head:
                    hkey = (
                        h.get("id") or f"{h.get('document_id')}:{h.get('chunk_index')}"
                    )
                    if hkey in seen or any(
                        (
                            r.get("id")
                            or f"{r.get('document_id')}:{r.get('chunk_index')}"
                        )
                        == hkey
                        for r in hits
                    ):
                        continue
                    head_new.append(h)
                hits = head_new + hits
                titles = []
                for r in hits:
                    key = (
                        r.get("id") or f"{r.get('document_id')}:{r.get('chunk_index')}"
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(
                        {
                            "id": r.get("id"),
                            "content": r.get("content") or r.get("text") or "",
                            "score": r.get("score"),
                            "document_id": r.get("document_id"),
                            "filename": resolved_fn,
                            "chunk_index": r.get("chunk_index")
                            if r.get("chunk_index") is not None
                            else (r.get("metadata") or {}).get("chunk_index"),
                            "source": r.get("source") or "filename_scoped",
                            "citations": [],
                        }
                    )
                    titles.append(resolved_fn)
                trace.add_step(
                    arm="chunk_scoped",
                    query=f"《{fn}》→{resolved_fn} {query}",
                    hit_count=len(titles),
                    hit_titles=titles,
                )
            except Exception as exc:
                logger.warning("scoped chunk step failed for %s: %s", fn, exc)
                trace.add_step(
                    arm="chunk_scoped", query=f"《{fn}》", hit_count=0, error=str(exc)
                )

    async def _run_compiled(self, authz, question, out, trace, *, db=None) -> None:
        try:
            from app.db.session import SessionLocal
            from app.services.clause_projection import load_clause_projections_for_query

            session = db or SessionLocal()
            try:
                from app.services.rls import apply_rls_context

                apply_rls_context(session, authz.tenant_id)
                projs = load_clause_projections_for_query(
                    db=session,
                    tenant_id=authz.tenant_id,
                    query=question,
                    authz=authz,
                    scope=getattr(self, "_filter_dict", None),
                )
            finally:
                if db is None:
                    session.close()
            out.extend(projs)
            titles = [p.get("filename") or "clause_projection" for p in projs]
            trace.add_step(
                arm="compiled",
                query=question,
                hit_count=len(projs),
                hit_titles=titles,
            )
        except Exception as exc:
            logger.warning("compiled step failed: %s", exc)
            trace.add_step(arm="compiled", query=question, hit_count=0, error=str(exc))

    async def _run_pageindex(self, authz, question, out, trace, *, db=None) -> None:
        """P2-4：PageIndex 長文件臂（feature-flagged）。"""
        from app.config import settings

        if not settings.PAGEINDEX_ENABLED:
            return
        try:
            from app.db.session import SessionLocal
            from app.models.knowledge_base import DocumentArtifact
            from app.services.pageindex import get_pageindex_retriever

            session = db or SessionLocal()
            try:
                from app.services.rls import apply_rls_context

                apply_rls_context(session, authz.tenant_id)
                from app.models.document import Document
                from app.models.knowledge_engine import KnowledgeBaseRevisionDocument
                from app.services.document_visibility import (
                    apply_document_visibility,
                    deny_set_allows,
                )

                # 查詢所有 pageindex_tree artifacts
                artifact_query = (
                    session.query(DocumentArtifact)
                    .join(Document, Document.id == DocumentArtifact.document_id)
                    .filter(
                        DocumentArtifact.artifact_type == "pageindex_tree",
                        DocumentArtifact.status == "active",
                    )
                )
                scope = getattr(self, "_filter_dict", None) or {}
                raw_revision_ids = scope.get("kb_revision_ids") or []
                revision_scoped = bool(raw_revision_ids) or "kb_revision_ids" in scope
                artifact_query = apply_document_visibility(
                    artifact_query,
                    authz=authz,
                    db=session,
                    require_completed=not revision_scoped,
                )
                if raw_revision_ids or "kb_revision_ids" in scope:
                    revision_ids = [UUID(str(value)) for value in raw_revision_ids]
                    from app.services.document_readiness import ready_revision_pairs

                    artifact_query = artifact_query.join(
                        KnowledgeBaseRevisionDocument,
                        (
                            KnowledgeBaseRevisionDocument.document_id
                            == DocumentArtifact.document_id
                        )
                        & (
                            KnowledgeBaseRevisionDocument.document_revision
                            == DocumentArtifact.revision
                        ),
                    ).filter(
                        KnowledgeBaseRevisionDocument.kb_revision_id.in_(revision_ids)
                    )
                    ready_pairs = ready_revision_pairs(
                        session,
                        tenant_id=authz.tenant_id,
                        kb_revision_ids=revision_ids,
                    )
                else:
                    artifact_query = artifact_query.filter(
                        DocumentArtifact.revision == Document.version
                    )
                    ready_pairs = None
                artifacts = [
                    artifact
                    for artifact in artifact_query.all()
                    if deny_set_allows(artifact.document_id, authz=authz)
                    and (
                        ready_pairs is None
                        or (artifact.document_id, artifact.revision) in ready_pairs
                    )
                ]
                if not artifacts:
                    return

                retriever = get_pageindex_retriever()
                for artifact in artifacts:
                    tree_data = artifact.metadata_json or {}
                    if not tree_data.get("pages"):
                        continue
                    from app.services.pageindex import PageIndexTree

                    tree = PageIndexTree(
                        document_id=tree_data.get("document_id", ""),
                        total_pages=tree_data.get("total_pages", 0),
                        pages=[],
                        section_ranges=tree_data.get("section_ranges", []),
                    )
                    pages = retriever.get_pages_for_query(tree, question, max_pages=5)
                    if pages:
                        chunk_ids = retriever.get_chunks_for_pages(tree, pages)
                        trace.add_step(
                            arm="pageindex",
                            query=question,
                            hit_count=len(chunk_ids),
                            hit_titles=[f"pages {pages[0]}-{pages[-1]}"],
                        )
            finally:
                if db is None:
                    session.close()
        except Exception as exc:
            logger.warning("pageindex step failed: %s", exc)
            trace.add_step(arm="pageindex", query=question, hit_count=0, error=str(exc))
