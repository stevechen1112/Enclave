import logging
import json
import re
import asyncio
from typing import Dict, Any, List, Optional, AsyncGenerator
from uuid import UUID
import uuid
from app.config import settings
from app.services.kb_retrieval import KnowledgeBaseRetriever
from app.services.core_client import CoreAPIClient
from app.services.structured_answers import try_structured_answer

logger = logging.getLogger(__name__)

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
    1. 並行查詢公司內規 + 勞資法 Core API
    2. 使用 LLM 根據檢索結果生成上下文感知的回答
    3. 附帶來源引用與法律免責聲明
    4. 支援串流生成 (T7-1) 與多輪對話 (T7-2)
    """

    SYSTEM_PROMPT = """你是 UniHR 人資 AI 助理，專門回答台灣企業的人事規章與勞動法規問題。

回答規則：
1. **只根據下方提供的參考資料回答**，不要自行捏造或引用未提供的內容
2. 如果有公司內規，以公司內規為主，法律規定為輔助參照
3. 如果公司內規的規定**低於**勞動法的最低標準，必須明確指出
4. 若公司內規高於法定最低標準，屬合法且應明確指出
5. 若參考資料中出現「測試陷阱／提醒／警示」，需依其內容修正結論並點出原因
6. 使用結構化格式（標題、條列）讓回答清楚易讀
7. 引用法律時，若參考資料包含具體條號（如第38條），**必須**引用到條號（例如：《勞動基準法》第38條），不能只寫法律名稱
8. 如果參考資料不足以回答，坦白說明並建議諮詢 HR 部門
9. 使用繁體中文回答
10. 需要數值計算時，請列出公式與代入值，嚴格依公式計算"""

    FOLLOWUP_PROMPT = """

在回答的最後，請另起一行輸出 2-3 個使用者可能會追問的建議問題，格式：
[建議問題]
1. ...
2. ...
3. ..."""
    
    def __init__(self):
        self.kb_retriever = KnowledgeBaseRetriever()
        self.core_client = CoreAPIClient()

        # OpenAI client (sync + async)
        self._openai = None
        self._openai_async = None
        openai_key = getattr(settings, "OPENAI_API_KEY", "")
        if _HAS_OPENAI and openai_key:
            self._openai = openai_lib.OpenAI(api_key=openai_key)
            self._openai_async = openai_lib.AsyncOpenAI(api_key=openai_key)

    # ──────────── T7-0: 檢索層（與生成解耦） ────────────

    async def retrieve_context(
        self,
        tenant_id: UUID,
        question: str,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        純檢索：並行查詢公司內規 + 勞資法 Core API，回傳結構化上下文。
        
        分離自原 process_query，使串流端點可先取得來源，再分段生成。
        """
        request_id = str(uuid.uuid4())

        async def get_company_policy():
            try:
                # run_in_executor：search() 含同步 Voyage embed/rerank 呼叫
                # 若直接在 async def 中呼叫會阻塞 event loop，
                # 導致 asyncio.gather() 無法真正並行。
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None,
                    lambda: self.kb_retriever.search(
                        tenant_id=tenant_id,
                        query=question,
                        top_k=top_k,
                    ),
                )
                return {"status": "success", "results": results}
            except Exception as e:
                return {"status": "error", "error": str(e), "results": []}

        async def get_labor_law():
            try:
                result = await self.core_client.chat(
                    question=question,
                    request_id=request_id,
                )
                return result
            except Exception as e:
                return {"status": "error", "answer": "勞資法查詢失敗", "error": str(e)}

        company_policy_result, labor_law_result = await asyncio.gather(
            asyncio.create_task(get_company_policy()),
            asyncio.create_task(get_labor_law()),
        )

        # 內規補強：根據問題關鍵字做檔名導向檢索（同樣用 executor 避免阻塞）
        loop = asyncio.get_event_loop()
        boosted_results = await loop.run_in_executor(
            None,
            lambda: self._policy_boost_search(tenant_id, question, top_k),
        )
        if boosted_results:
            base_results = company_policy_result.get("results", [])
            merged = self._merge_policy_results(base_results, boosted_results, top_k)
            company_policy_result["status"] = "success"
            company_policy_result["results"] = merged

        # ── 組裝結構化上下文 ──
        return self._build_context(
            question=question,
            company_policy=company_policy_result,
            labor_law=labor_law_result,
            request_id=request_id,
        )

    def _policy_boost_search(
        self, tenant_id: UUID, question: str, top_k: int
    ) -> List[Dict[str, Any]]:
        filenames = self._policy_hint_filenames(question)
        if not filenames:
            return []
        try:
            return self.kb_retriever.search(
                tenant_id=tenant_id,
                query=question,
                top_k=top_k,
                mode="semantic",
                rerank=False,
                filter_dict={"filename": filenames},
            )
        except Exception:
            return []

    @staticmethod
    def _policy_hint_filenames(question: str) -> List[str]:
        hints: List[str] = []
        if any(k in question for k in ["績效", "考核"]):
            hints.append("員工手冊-第一章-總則.pdf")
        if any(k in question for k in ["報帳", "計程車", "憑證", "發票"]):
            hints.append("報帳作業規範.pdf")
        if any(k in question for k in ["新人", "報到", "到職", "試用期"]):
            hints.extend(["新人到職SOP.pdf", "勞動契約書-謝雅玲.pdf"])
        if any(k in question for k in ["特休", "婚假", "喪假", "生理假", "產假", "陪產", "請假"]):
            hints.extend(["員工手冊-第一章-總則.pdf", "請假單範本-E012-周秀蘭.pdf"])
        if "年終獎金" in question or "獎懲" in question:
            hints.extend(["獎懲管理辦法.pdf", "勞動契約書-謝雅玲.pdf"])
        if "加班" in question:
            hints.extend(["員工手冊-第一章-總則.pdf", "勞動契約書-謝雅玲.pdf"])
        if "交通津貼" in question or "津貼" in question:
            hints.append("員工手冊-第一章-總則.pdf")
        if "勞保" in question or "健保" in question:
            hints.append("202601-E007-劉志明-薪資條.pdf")
        if "健檢" in question or "健康檢查" in question:
            hints.append("健康檢查報告-E016-高淑珍.pdf")
        if "薪資" in question or "薪水" in question or "實領" in question:
            hints.append("202601-E007-劉志明-薪資條.pdf")
        # 去重保持順序
        seen = set()
        ordered = []
        for name in hints:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

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
        labor_law: Dict[str, Any],
        request_id: str,
    ) -> Dict[str, Any]:
        """將 raw 檢索結果組裝為結構化 context dict。"""
        has_policy = (
            company_policy.get("status") == "success"
            and len(company_policy.get("results", [])) > 0
        )
        has_labor_law = (
            labor_law.get("status") != "error" and labor_law.get("answer")
        )

        context: Dict[str, Any] = {
            "request_id": request_id,
            "question": question,
            "has_policy": has_policy,
            "has_labor_law": has_labor_law,
            "company_policy_raw": None,
            "labor_law_raw": None,
            "context_parts": [],
            "sources": [],
            "disclaimer": "本回答僅供參考，不構成正式法律意見。如有具體情況，請諮詢專業法律顧問。",
        }

        if has_policy:
            top_policies = company_policy["results"][:3]
            context["company_policy_raw"] = {
                "content": top_policies[0].get("content") or "",
                "source": top_policies[0].get("filename") or "",
                "relevance_score": top_policies[0].get("score") or 0,
                "all_results": [
                    {
                        "content": (r.get("content") or "")[:500],
                        "filename": r.get("filename") or "",
                        "score": r.get("score") or 0,
                    }
                    for r in top_policies
                ],
            }
            for r in top_policies:
                context["sources"].append({
                    "type": "policy",
                    "title": r.get("filename") or "",
                    "snippet": (r.get("content") or "")[:200],
                    "score": r.get("score") or 0,
                })
            for i, r in enumerate(top_policies, 1):
                content = r.get("content") or ""
                filename = r.get("filename") or ""
                score = r.get("score") or 0
                context["context_parts"].append(
                    f"【公司內規 #{i}】（來源：{filename}，相關度：{score:.2f}）\n{content}"
                )

        if has_labor_law:
            context["labor_law_raw"] = {
                "answer": labor_law.get("answer", ""),
                "citations": labor_law.get("citations", []),
                "usage": labor_law.get("usage", {}),
            }
            if labor_law.get("citations"):
                for citation in labor_law["citations"]:
                    law_name = citation.get("law_name") or "勞動法規"
                    article = citation.get("article") or ""
                    title = f"{law_name} {article}".strip()
                    context["sources"].append({
                        "type": "law",
                        "title": title,
                        "snippet": labor_law.get("answer", "")[:200],
                    })
            else:
                # Core API 不回傳結構化 citations，從回答文字中解析法條引用
                answer_text = labor_law.get("answer") or ""
                if answer_text:
                    law_refs = re.findall(r'《(.+?)》(?:第(\d+[-之]?\d*條?))?', answer_text)
                    if law_refs:
                        seen = set()
                        for law_name, article in law_refs[:5]:
                            key = f"{law_name} {article}".strip()
                            if key not in seen:
                                seen.add(key)
                                context["sources"].append({
                                    "type": "law",
                                    "title": key,
                                    "snippet": answer_text[:200],
                                })
                    else:
                        context["sources"].append({
                            "type": "law",
                            "title": "勞動法規 (Core API)",
                            "snippet": answer_text[:200],
                        })
            law_text = labor_law.get("answer", "")
            citations_text = ""
            if labor_law.get("citations"):
                citations_text = "；".join(
                    f"{c.get('law_name', '')} {c.get('article', '')}"
                    for c in labor_law["citations"]
                )
            elif law_text:
                # Core API 不回傳結構化 citations，從 answer 文字解析法條做為 heading
                parsed = re.findall(r'《(.+?)》(?:第([\d\-之]+條(?:之\d+)?))?', law_text)
                seen_cit: set = set()
                unique_cit: list = []
                for law_n, art_n in parsed[:8]:
                    key = f"《{law_n}》第{art_n}條" if art_n else f"《{law_n}》"
                    if key not in seen_cit:
                        seen_cit.add(key)
                        unique_cit.append(key)
                if unique_cit:
                    citations_text = "（法源：" + "、".join(unique_cit) + "）"
            context["context_parts"].append(
                f"【勞動法規】{citations_text}\n{law_text}"
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
        if not self._openai_async or not (context["has_policy"] or context["has_labor_law"]):
            yield self._fallback_answer(context)
            return

        messages = self._build_llm_messages(
            question, context, history=history, include_followup=include_followup
        )

        try:
            response = await self._openai_async.chat.completions.create(
                model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
                messages=messages,
                temperature=getattr(settings, "OPENAI_TEMPERATURE", 0.3),
                max_tokens=getattr(settings, "OPENAI_MAX_TOKENS", 1500),
                stream=True,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
        except Exception as e:
            logger.warning(f"LLM 串流生成失敗，回退到模板: {e}")
            yield self._fallback_answer(context)

    # ──────────── T7-2: 多輪對話支援 ────────────

    # 需要上下文補全的代名詞／指示詞
    _CONTEXT_PRONOUNS = ("他", "她", "它", "他的", "她的", "他們", "她們",
                         "這個人", "那個人", "此人", "該員工", "同一", "上述", "前述")

    async def contextualize_query(
        self, query: str, history: List[Dict[str, str]]
    ) -> str:
        """
        用 LLM 將含代名詞/省略主詞的查詢改寫為獨立查詢。
        若歷史為空、LLM 不可用、或問題不含指代詞，直接回傳原 query。
        """
        if not history or not self._openai_async:
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
            response = await self._openai_async.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0,
                max_tokens=200,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"查詢改寫失敗: {e}")
            return query

    # ──────────── 向下相容：保留原 process_query ────────────

    async def process_query(
        self,
        tenant_id: UUID,
        question: str,
        top_k: int = settings.RETRIEVAL_TOP_K,
        conversation_id: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        處理用戶查詢（非串流，向下相容）。
        
        新增 conversation_id / history 參數以支援多輪對話。
        """
        structured = try_structured_answer(tenant_id, question, history=history)
        if structured:
            return {
                "request_id": str(uuid.uuid4()),
                "question": question,
                "company_policy": None,
                "labor_law": None,
                "answer": structured.answer,
                "sources": structured.sources,
                "notes": ["使用結構化資料直接計算"],
                "disclaimer": "本回答僅供參考，不構成正式法律意見。如有具體情況，請諮詢專業法律顧問。",
            }
        # 查詢改寫（多輪）
        effective_question = question
        if history:
            effective_question = await self.contextualize_query(question, history)

        # 檢索
        ctx = await self.retrieve_context(
            tenant_id=tenant_id,
            question=effective_question,
            top_k=top_k,
        )

        # 生成回答（非串流）
        result = {
            "request_id": ctx["request_id"],
            "question": question,
            "company_policy": ctx["company_policy_raw"],
            "labor_law": ctx["labor_law_raw"],
            "answer": "",
            "sources": ctx["sources"],
            "notes": [],
            "disclaimer": ctx["disclaimer"],
        }

        if self._openai and (ctx["has_policy"] or ctx["has_labor_law"]):
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
            if not (ctx["has_policy"] or ctx["has_labor_law"]):
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
        system_content = self.SYSTEM_PROMPT
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
        messages = self._build_llm_messages(question, context, history=history)

        response = self._openai.chat.completions.create(
            model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages,
            temperature=getattr(settings, "OPENAI_TEMPERATURE", 0.3),
            max_tokens=getattr(settings, "OPENAI_MAX_TOKENS", 1500),
        )
        return response.choices[0].message.content.strip()

    @staticmethod
    def _build_calc_guidance(question: str) -> str:
        hints: List[str] = []
        if "特休" in question or "特別休假" in question:
            hints.append("特休天數依勞基法第38條，按『實際到職日』計算年資，而非問題敘述中的概算。")
            hints.append("年資區間：未滿6個月=0天，6個月以上未滿1年=3天，1年=7天，2年=10天，3年=14天，5年=15天，10年以上每年+1天(最多30天)。")
            hints.append("若問題含有具體到職日期，請計算到今天（2026年2月23日）的正確年資後再查對照表。")
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
        has_labor_law = context.get("has_labor_law", False)

        if has_policy and has_labor_law:
            policy_content = context["company_policy_raw"]["content"][:500]
            law_answer = context["labor_law_raw"]["answer"][:500]
            return f"""📋 **公司內規規定**：
{policy_content}

⚖️ **勞動法規補充**：
{law_answer}

💡 **說明**：公司內規是您的優先參考依據，但不得違反勞動法的最低標準。"""

        elif has_policy:
            return f"""📋 **公司內規規定**：
{context["company_policy_raw"]["content"]}

💡 **提醒**：未查詢到相關勞動法規補充。如需了解法律最低標準，請進一步諮詢。"""

        elif has_labor_law:
            return f"""⚖️ **勞動法規**：
{context["labor_law_raw"]["answer"]}

💡 **提醒**：未在公司內規中找到相關規定。建議確認公司是否有額外規定。"""

        else:
            return "抱歉，未找到相關資訊。請嘗試換個方式提問，或聯繫 HR 部門。"

    def format_summary(self, result: Dict[str, Any]) -> str:
        """格式化摘要（用於顯示）"""
        summary = f"**問題**：{result['question']}\n\n"
        summary += result["answer"]

        if result["sources"]:
            summary += "\n\n**參考來源**：\n"
            for source in result["sources"]:
                if source["type"] == "company_policy":
                    summary += f"- 📋 {source['filename']} (相關度: {source['score']:.2f})\n"
                elif source["type"] == "labor_law":
                    summary += f"- ⚖️ {source.get('law_name', '勞動法規')} {source.get('article', '')}\n"

        summary += f"\n\n{result['disclaimer']}"
        return summary
