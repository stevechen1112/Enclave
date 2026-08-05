"""source_verifier 逐字溯源稽核的合約測試。

涵蓋：正規化、建議問題剝除、JSON 解析、逐字比對判定、
以及 ChatOrchestrator 三種模式（off/shadow/enforce）的行為分界。
"""
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, ".")

from app.services.source_verifier import (
    _normalize,
    strip_suggestions,
    verify_answer,
)


def _fake_client(payload):
    """回傳固定 JSON 字串的假 async OpenAI client。"""
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    msg = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=msg)
    resp = types.SimpleNamespace(choices=[choice])
    completions = types.SimpleNamespace(create=AsyncMock(return_value=resp))
    chat = types.SimpleNamespace(completions=completions)
    return types.SimpleNamespace(chat=chat)


CHUNKS = [
    "【113年營所稅申報書_E42八策.pdf】\n營利事業名稱：八策數位股份有限公司\n統一編號：83028948",
    "【1140213-報價單.docx】\n未稅金額 | 9,600 元<br/>匯款銀行：玉山銀行",
]


class TestNormalize(unittest.TestCase):
    def test_whitespace_and_table_markup_removed(self):
        self.assertEqual(_normalize("未稅金額 | 9,600 元<br/>"), "未稅金額9,600元")

    def test_dash_variants_removed(self):
        self.assertEqual(_normalize("2024－2025"), _normalize("2024—2025"))

    def test_nfkc_fullwidth(self):
        self.assertEqual(_normalize("ＡＢＣ１２３"), "ABC123")


class TestStripSuggestions(unittest.TestCase):
    def test_strips_followup_block(self):
        ans = "答案是 42。\n\n[建議問題]\n1. 還有嗎？\n2. 為什麼？"
        self.assertEqual(strip_suggestions(ans), "答案是 42。")

    def test_no_block_unchanged(self):
        self.assertEqual(strip_suggestions("答案是 42。"), "答案是 42。")


class TestVerifyAnswer(unittest.IsolatedAsyncioTestCase):
    async def test_all_claims_verified(self):
        client = _fake_client({
            "claims": [
                {"claim": "公司名稱是八策數位股份有限公司",
                 "source_quote": "營利事業名稱：八策數位股份有限公司"},
                {"claim": "統一編號 83028948", "source_quote": "統一編號：83028948"},
            ],
            "unsupported": [],
        })
        r = await verify_answer("公司名稱？", "公司名稱是八策數位股份有限公司，統編 83028948。",
                                CHUNKS, client, "fake-model")
        self.assertTrue(r.verified)
        self.assertEqual(r.total_claims, 2)
        self.assertEqual(r.reason, "ok")

    async def test_unverifiable_quote_moves_to_unsupported(self):
        client = _fake_client({
            "claims": [
                {"claim": "公司名稱是八策數位股份有限公司",
                 "source_quote": "營利事業名稱：八策數位股份有限公司"},
                {"claim": "資本額五千萬", "source_quote": "資本額：新台幣五千萬元整"},
            ],
            "unsupported": [],
        })
        r = await verify_answer("基本資料？", "公司八策數位，資本額五千萬。",
                                CHUNKS, client, "fake-model")
        self.assertFalse(r.verified)
        self.assertEqual(len(r.verified_claims), 1)
        self.assertEqual(r.unsupported_claims, ["資本額五千萬"])
        self.assertEqual(r.reason, "unverified_claims")

    async def test_llm_declared_unsupported_respected(self):
        client = _fake_client({"claims": [], "unsupported": ["董事長私人手機"]})
        r = await verify_answer("私人手機？", "董事長私人手機是 09xx。",
                                CHUNKS, client, "fake-model")
        self.assertFalse(r.verified)
        self.assertEqual(r.unsupported_claims, ["董事長私人手機"])

    async def test_table_formatted_quote_matches(self):
        # chunk 裡是表格排版（| 與 <br/>），quote 是連續文字 → 正規化後應命中
        client = _fake_client({
            "claims": [{"claim": "未稅金額 9,600 元", "source_quote": "未稅金額9,600元"}],
            "unsupported": [],
        })
        r = await verify_answer("金額？", "未稅金額 9,600 元。", CHUNKS, client, "fake-model")
        self.assertTrue(r.verified)

    async def test_invalid_json(self):
        client = _fake_client("這不是 JSON")
        r = await verify_answer("q", "答案是八策。", CHUNKS, client, "fake-model")
        self.assertFalse(r.verified)
        self.assertEqual(r.reason, "llm_no_json")

    async def test_llm_exception(self):
        completions = types.SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("boom")))
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))
        r = await verify_answer("q", "答案是八策。", CHUNKS, client, "fake-model")
        self.assertFalse(r.verified)
        self.assertEqual(r.reason, "llm_error")

    async def test_pure_refusal_answer_passes(self):
        # 純拒答文沒有事實論點 → 不視為幻覺
        client = _fake_client({"claims": [], "unsupported": []})
        r = await verify_answer("q", "目前知識庫中沒有足夠的相關文件。",
                                CHUNKS, client, "fake-model")
        self.assertTrue(r.verified)
        self.assertEqual(r.reason, "no_factual_claims")

    async def test_empty_context(self):
        client = _fake_client({"claims": [], "unsupported": []})
        r = await verify_answer("q", "答案", [], client, "fake-model")
        self.assertFalse(r.verified)
        self.assertEqual(r.reason, "empty_answer_or_context")

    async def test_derived_claim_with_verbatim_basis_passes(self):
        # 民國→西元換算：引述逐字存在即可通過，推導由稽核 LLM 具結
        client = _fake_client({
            "claims": [
                {"claim": "這是西元2024年度的申報書", "type": "derived",
                 "basis_quotes": ["營利事業名稱：八策數位股份有限公司"],
                 "derivation": "民國113年=西元2024年"},
            ],
            "unsupported": [],
        })
        r = await verify_answer("年度？", "這是西元2024年度的申報書。",
                                CHUNKS, client, "fake-model")
        self.assertTrue(r.verified)
        self.assertEqual(r.verified_claims[0]["type"], "derived")

    async def test_derived_claim_with_fabricated_basis_fails(self):
        client = _fake_client({
            "claims": [
                {"claim": "這是西元2024年度的申報書", "type": "derived",
                 "basis_quotes": ["文件根本沒有這句話"],
                 "derivation": "換算"},
            ],
            "unsupported": [],
        })
        r = await verify_answer("年度？", "這是西元2024年度的申報書。",
                                CHUNKS, client, "fake-model")
        self.assertFalse(r.verified)
        self.assertEqual(r.unsupported_claims, ["這是西元2024年度的申報書"])

    async def test_derived_claim_empty_basis_fails(self):
        client = _fake_client({
            "claims": [
                {"claim": "推導但沒給依據", "type": "derived", "basis_quotes": []},
            ],
            "unsupported": [],
        })
        r = await verify_answer("q", "推導但沒給依據。", CHUNKS, client, "fake-model")
        self.assertFalse(r.verified)


class TestOrchestratorModes(unittest.IsolatedAsyncioTestCase):
    """模式分界：off 不稽核；shadow 稽核但輸出不變。"""

    def _make_orchestrator(self):
        from app.services.chat_orchestrator import ChatOrchestrator

        orch = ChatOrchestrator.__new__(ChatOrchestrator)
        orch._openai_async = object()  # 只需非 None
        orch._internal_async = None
        orch._llm_model = "m"
        orch._internal_model = None
        orch._fallback_answer = lambda ctx: "fallback"
        return orch

    def _context(self):
        return {
            "has_policy": True,
            "context_parts": CHUNKS,
            "sources": [],
            "retrieval": {"query_plan": {"intent": "fact"}},
        }

    async def _collect(self, orch, mode):
        ctx = self._context()
        with patch("app.services.chat_orchestrator.settings") as s:
            s.SOURCE_VERIFY_MODE = mode
            s.OPENAI_MAX_TOKENS = 4000
            s.OPENAI_TEMPERATURE = 0.3
            s.SOURCE_VERIFY_USE_INTERNAL_LLM = True
            chunks = []
            async for piece in orch.stream_answer("q", ctx):
                chunks.append(piece)
        return "".join(chunks), ctx

    async def test_off_mode_skips_verification(self):
        orch = self._make_orchestrator()

        async def fake_raw(q, c, h, i, extra_system_note=""):
            yield "回答內容"

        orch._stream_answer_raw = fake_raw
        with patch("app.services.source_verifier.verify_answer",
                   new=AsyncMock(side_effect=AssertionError("off 模式不應呼叫稽核"))):
            answer, ctx = await self._collect(orch, "off")
        self.assertEqual(answer, "回答內容")
        self.assertNotIn("source_verification", ctx)

    async def test_shadow_verifies_but_output_unchanged(self):
        from app.services.source_verifier import SourceVerifyResult

        orch = self._make_orchestrator()

        async def fake_raw(q, c, h, i, extra_system_note=""):
            yield "回答內容"

        orch._stream_answer_raw = fake_raw
        fake_result = SourceVerifyResult(False, total_claims=1,
                                         unsupported_claims=["x"], reason="unverified_claims")
        with patch("app.services.source_verifier.verify_answer",
                   new=AsyncMock(return_value=fake_result)):
            answer, ctx = await self._collect(orch, "shadow")
        # shadow：即使未通過，輸出也必須原樣
        self.assertEqual(answer, "回答內容")
        self.assertIn("source_verification", ctx)
        self.assertFalse(ctx["source_verification"]["verified"])


if __name__ == "__main__":
    unittest.main()
