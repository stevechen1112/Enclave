"""
Phase 10 — AI 自動分類引擎 (Classifier)

對每個被 file_watcher 發現的檔案進行兩段分析：
  1. 檔名解析：用正規表示式 + LLM 從檔名提取結構化欄位
  2. 內容摘要分析：讀取文件前 500 tokens，用 LLM 判斷類型與實體

輸出 ClassificationProposal，包含：
  - 建議分類（來自可設定的 taxonomy）
  - 建議標籤（日期、當事人、案件類型、狀態等）
  - 信心分數（0.0 ~ 1.0）
  - 判斷依據摘要（顯示在審核介面，讓人類理解 AI 為何這樣判斷）

分類 taxonomy 可設定化：
  - 預設行業範本：法律、會計、醫療、製造
  - 管理員可在後台自訂分類標籤與欄位
  - 設定存於 organization_settings 資料表
"""

import re
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 預設 taxonomy ──────────────────────────────────────────────────────────────

DEFAULT_TAXONOMY: Dict[str, list] = {
    "合約文件": ["勞動契約", "保密協議", "委任合約", "合作協議", "租賃合約", "其他合約"],
    "財務報表": ["資產負債表", "損益表", "現金流量表", "預算書", "費用申請", "其他財務"],
    "法律文件": ["起訴狀", "訴訟答辯", "法院裁定", "律師函", "法律意見書", "其他法律"],
    "會議記錄": ["董事會", "股東會", "行政會議", "專案會議", "其他會議"],
    "政策規章": ["人事規章", "作業程序", "安全規範", "品質標準", "其他規章"],
    "報告分析": ["市場分析", "績效報告", "稽核報告", "技術報告", "其他報告"],
    "往來信函": ["一般信函", "詢問函", "通知書", "催繳函", "其他信函"],
    "其他文件": ["其他"],
}

# ── 檔名正規表示式模式 ──────────────────────────────────────────────────────────

_DATE_PATTERN = re.compile(
    r"(\d{8}|\d{4}[-/]\d{2}[-/]\d{2}|\d{4}年\d{1,2}月\d{1,2}日|\d{6})"
)
_STATUS_WORDS = {"初稿", "草案", "定稿", "定案", "最終版", "v1", "v2", "final",
                 "draft", "revised", "amended", "已簽", "未簽", "作廢", "存檔"}
_CONTRACT_WORDS = {"合約", "合同", "契約", "協議", "agreement", "contract"}
_FINANCIAL_WORDS = {"報表", "財報", "預算", "費用", "invoice", "receipt", "report"}
_LEGAL_WORDS = {"起訴", "答辯", "裁定", "律師", "法院", "判決", "調解"}


@dataclass
class ClassificationProposal:
    """AI 分類提案，送入審核佇列供人工確認。"""
    file_path: str
    file_name: str
    file_size: int
    file_ext: str

    # AI 提案結果
    suggested_category: str = ""
    suggested_subcategory: str = ""
    suggested_tags: Dict[str, str] = field(default_factory=dict)
    confidence_score: float = 0.0
    reasoning: str = ""

    # 狀態
    needs_review: bool = True
    error: Optional[str] = None


class DocumentClassifier:
    """LLM 驅動的文件分類引擎。"""

    CONFIDENCE_THRESHOLD = 0.6

    def __init__(self, llm_client=None, taxonomy: Dict[str, Any] = None):
        self.llm_client = llm_client
        self.taxonomy = taxonomy or DEFAULT_TAXONOMY

    # ── 公開 API ────────────────────────────────────────────────────────────────

    async def classify_file(self, file_path: Path) -> ClassificationProposal:
        """對單一檔案執行分類，回傳提案。"""
        stat = file_path.stat() if file_path.exists() else None
        proposal = ClassificationProposal(
            file_path=str(file_path),
            file_name=file_path.name,
            file_size=stat.st_size if stat else 0,
            file_ext=file_path.suffix.lower(),
        )

        try:
            # 1) 從檔名提取初步訊號
            fn_tags = self._parse_filename(file_path.name)
            proposal.suggested_tags.update(fn_tags)

            # 2) 讀取文件頭部內容
            head_text = await self._analyze_content_head(file_path)

            # 3) LLM 分類
            if self.llm_client is not None:
                await self._llm_classify(proposal, head_text)
            else:
                # 無 LLM 時退化為關鍵字規則
                self._rule_classify(proposal)

            proposal.needs_review = proposal.confidence_score < self.CONFIDENCE_THRESHOLD

        except Exception as exc:
            logger.warning("classify_file error %s: %s", file_path, exc)
            proposal.error = str(exc)
            proposal.confidence_score = 0.0
            proposal.needs_review = True

        return proposal

    # ── 私有：檔名解析 ──────────────────────────────────────────────────────────

    def _parse_filename(self, filename: str) -> Dict[str, str]:
        """從檔名提取結構化欄位（日期、狀態等）。"""
        tags: Dict[str, str] = {}
        stem = Path(filename).stem

        # 日期
        m = _DATE_PATTERN.search(stem)
        if m:
            tags["date"] = m.group(0)

        # 狀態關鍵字
        stem_lower = stem.lower()
        for kw in _STATUS_WORDS:
            if kw in stem_lower:
                tags["status"] = kw
                break

        # 人名（中文 2-4 字夾在 _ 或空格之間）
        person_m = re.search(r"[_\s－\-]([^\d_\s－\-]{2,4})[_\s－\-]", f"_{stem}_")
        if person_m:
            cand = person_m.group(1)
            # 過濾掉純英文或數字
            if re.search(r"[\u4e00-\u9fff]", cand):
                tags["person"] = cand

        return tags

    # ── 私有：內容讀取 ──────────────────────────────────────────────────────────

    async def _analyze_content_head(self, file_path: Path, char_limit: int = 1200) -> str:
        """讀取文件前 N 字作為 LLM 分析材料。"""
        try:
            text = await self._extract_text_head(file_path, char_limit)
            return text
        except Exception as exc:
            logger.debug("content head extract failed for %s: %s", file_path, exc)
            return ""

    async def _extract_text_head(self, file_path: Path, char_limit: int) -> str:
        """輕量文字提取（優先純文字，不可時傳回空字串）。"""
        ext = file_path.suffix.lower()
        loop_text = ""

        try:
            if ext in {".txt", ".md", ".csv", ".log"}:
                with open(file_path, encoding="utf-8", errors="replace") as f:
                    loop_text = f.read(char_limit)

            elif ext == ".pdf":
                try:
                    import pdfplumber
                    with pdfplumber.open(file_path) as pdf:
                        for page in pdf.pages[:3]:
                            loop_text += (page.extract_text() or "")
                            if len(loop_text) >= char_limit:
                                break
                except ImportError:
                    pass

            elif ext in {".docx"}:
                try:
                    from docx import Document as DocxDocument
                    doc = DocxDocument(str(file_path))
                    for para in doc.paragraphs[:20]:
                        loop_text += para.text + "\n"
                        if len(loop_text) >= char_limit:
                            break
                except ImportError:
                    pass

        except Exception:
            pass

        return loop_text[:char_limit]

    # ── 私有：規則分類（無 LLM 退化路徑）────────────────────────────────────────

    def _rule_classify(self, proposal: ClassificationProposal) -> None:
        """純關鍵字規則分類，無 LLM 時使用。"""
        name_lower = proposal.file_name.lower()

        if any(kw in name_lower for kw in _CONTRACT_WORDS):
            proposal.suggested_category = "合約文件"
            proposal.confidence_score = 0.45
        elif any(kw in name_lower for kw in _FINANCIAL_WORDS):
            proposal.suggested_category = "財務報表"
            proposal.confidence_score = 0.45
        elif any(kw in name_lower for kw in _LEGAL_WORDS):
            proposal.suggested_category = "法律文件"
            proposal.confidence_score = 0.45
        else:
            proposal.suggested_category = "其他文件"
            proposal.confidence_score = 0.2

        proposal.reasoning = "規則比對（無 LLM）"

    # ── 私有：LLM 分類 ──────────────────────────────────────────────────────────

    async def _llm_classify(self, proposal: ClassificationProposal, head_text: str) -> None:
        """呼叫 LLM 進行分類並解析 JSON 回應。"""
        taxonomy_str = "\n".join(
            f"  {cat}: {', '.join(subs)}" for cat, subs in self.taxonomy.items()
        )
        tags_hint = ", ".join(f"{k}={v}" for k, v in proposal.suggested_tags.items()) or "無"

        system_prompt = (
            "你是企業文件分類助手。根據文件名稱和內容片段，"
            "從指定分類清單中選出最合適的一級分類和二級分類，"
            "並輸出 JSON 格式結果，不要輸出其他文字。\n\n"
            f"可用分類：\n{taxonomy_str}"
        )
        user_message = (
            f"檔案名稱：{proposal.file_name}\n"
            f"檔名標籤線索：{tags_hint}\n"
            f"內容片段（前 600 字）：\n{head_text[:600] or '（無法讀取內容）'}\n\n"
            "請以 JSON 回應，格式：\n"
            '{"category": "一級分類", "subcategory": "二級分類", '
            '"confidence": 0.75, "reasoning": "判斷依據一句話"}'
        )

        try:
            # LLMClient.complete() 是同步的，在 executor 中執行
            import asyncio
            raw = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.llm_client.complete(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    temperature=0.1,
                    max_tokens=200,
                ),
            )
            self._parse_llm_response(proposal, raw)
        except Exception as exc:
            logger.warning("LLM classify failed: %s", exc)
            self._rule_classify(proposal)

    def _parse_llm_response(self, proposal: ClassificationProposal, raw: str) -> None:
        """解析 LLM 的 JSON 回應，填入 proposal。"""
        try:
            # 處理 LLM 可能包裹 markdown code fence 的情況
            text = raw.strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-z]*\n?", "", text)
                text = re.sub(r"\n?```$", "", text)

            data = json.loads(text)
            proposal.suggested_category = data.get("category", "其他文件")
            proposal.suggested_subcategory = data.get("subcategory", "")
            proposal.confidence_score = float(data.get("confidence", 0.5))
            proposal.reasoning = data.get("reasoning", "")

        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("parse LLM response failed: %s | raw=%r", exc, raw[:200])
            self._rule_classify(proposal)


# ── 全局單例工廠 ────────────────────────────────────────────────────────────────

_classifier: Optional[DocumentClassifier] = None


def get_classifier() -> DocumentClassifier:
    """取得全局 DocumentClassifier（懶初始化）。"""
    global _classifier
    if _classifier is None:
        try:
            from app.services.llm_client import LLMClient
            from app.services.deployment_mode import resolve_runtime_profiles_no_db
            # 分類器使用 INTERNAL_LLM_PROVIDER（預設 Ollama），不消耗雲端 API 額度
            runtime = resolve_runtime_profiles_no_db()
            internal_cfg = runtime.get("internal", {})
            internal_provider = str(internal_cfg.get("provider", "ollama")).lower()
            if internal_provider == "ollama":
                ollama_url = str(internal_cfg.get("base_url", "http://host.docker.internal:11434"))
                ollama_model = str(internal_cfg.get("model", "gemma3:27b"))
                llm = LLMClient(provider="ollama", model=ollama_model, base_url=ollama_url)
            elif internal_provider in ("gemini", "openai"):
                llm = LLMClient(provider=internal_provider, model=str(internal_cfg.get("model", "")) or None)
            else:
                llm = LLMClient()
            _classifier = DocumentClassifier(llm_client=llm)
        except Exception as exc:
            logger.warning("get_classifier: LLM unavailable, using rules only: %s", exc)
            _classifier = DocumentClassifier(llm_client=None)
    return _classifier

