"""
P3-4：Docling Parser Ablation — 條件式評估 Docling Serve。

稽核文件 §8.3：
- 不因 OpenRAG 有 Docling 就直接加服務
- 先用表格／掃描 corpus 做 parser ablation
- 若 Docling 對表格、版面或多格式有實證增量，再作 Enterprise optional sidecar

本模組提供 Docling 整合骨架 + ablation 比較框架。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """解析結果。"""
    text: str = ""
    pages: List[Dict[str, Any]] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    elapsed_seconds: float = 0.0
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error and bool(self.text)


@dataclass
class AblationComparison:
    """Parser ablation 比較結果。"""
    file_path: str = ""
    file_type: str = ""
    results: Dict[str, ParseResult] = field(default_factory=dict)  # provider → result

    def get_winner(self) -> Tuple[str, str]:
        """判定哪個 parser 勝出。

        Returns:
            (winner_provider, reason)
        """
        if not self.results:
            return ("", "no results")

        if len(self.results) == 1:
            provider = list(self.results.keys())[0]
            return (provider, "no comparison (only one parser)")

        # 比較維度：
        # 1. 成功率
        # 2. 文字量
        # 3. 表格數
        # 4. 延遲

        scores: Dict[str, float] = {}
        for provider, result in self.results.items():
            score = 0.0
            if result.success:
                score += 40  # 成功基礎分
                score += min(len(result.text) / 1000, 30)  # 文字量（最多 30 分）
                score += min(len(result.tables) * 5, 20)  # 表格數（最多 20 分）
                score += max(0, 10 - result.elapsed_seconds)  # 延遲（最多 10 分）
            scores[provider] = score

        winner = max(scores, key=scores.get)
        reason = f"score={scores[winner]:.1f} (text={len(self.results[winner].text)}, tables={len(self.results[winner].tables)}, elapsed={self.results[winner].elapsed_seconds:.1f}s)"
        return (winner, reason)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "file_type": self.file_type,
            "results": {
                p: {
                    "success": r.success,
                    "text_length": len(r.text),
                    "tables": len(r.tables),
                    "pages": len(r.pages),
                    "elapsed_seconds": r.elapsed_seconds,
                    "error": r.error,
                    "provider": r.provider,
                }
                for p, r in self.results.items()
            },
            "winner": self.get_winner(),
        }


class DoclingParser:
    """Docling Serve 整合。

    借鑑 OpenRAG flows/components/docling_remote.py：
    - polling service
    - health UI
    - 長 OCR 不占 flow slot

    Enclave 條件式採用：
    - 預設 OFF
    - 需 ablation 證明增量
    """

    def __init__(self, base_url: str = "http://docling-serve:5001", timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        """檢查 Docling Serve 是否可用。"""
        from app.config import settings
        if not settings.DOCLING_ENABLED:
            return False

        try:
            import httpx
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    def parse(self, file_path: str, file_type: str = "") -> ParseResult:
        """透過 Docling Serve 解析文件。

        Args:
            file_path: 本機檔案路徑
            file_type: 檔案類型（可選）

        Returns:
            ParseResult
        """
        import time
        t0 = time.time()

        try:
            import httpx

            with open(file_path, "rb") as f:
                files = {"file": (file_path, f)}
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(
                        f"{self.base_url}/parse",
                        files=files,
                        params={"format": "json"},
                    )

            elapsed = time.time() - t0

            if resp.status_code != 200:
                return ParseResult(
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    provider="docling",
                    elapsed_seconds=elapsed,
                )

            data = resp.json()
            return ParseResult(
                text=data.get("text", ""),
                pages=data.get("pages", []),
                tables=data.get("tables", []),
                metadata=data.get("metadata", {}),
                provider="docling",
                elapsed_seconds=elapsed,
            )

        except Exception as exc:
            return ParseResult(
                error=str(exc),
                provider="docling",
                elapsed_seconds=time.time() - t0,
            )


class ParserAblationRunner:
    """Parser ablation 比較框架。

    比較現有 parser（native / RAGFlow / cloud OCR）與 Docling，
    用表格／掃描 corpus 證明增量。
    """

    def __init__(self):
        self.docling = DoclingParser()

    def run_ablation(
        self,
        file_path: str,
        file_type: str = "",
        include_native: bool = True,
        include_docling: bool = True,
    ) -> AblationComparison:
        """對單一檔案跑 parser ablation。

        Args:
            file_path: 檔案路徑
            file_type: 檔案類型
            include_native: 是否跑 native parser
            include_docling: 是否跑 Docling

        Returns:
            AblationComparison
        """
        comparison = AblationComparison(file_path=file_path, file_type=file_type)

        if include_native:
            comparison.results["native"] = self._parse_native(file_path, file_type)

        if include_docling and self.docling.is_available():
            comparison.results["docling"] = self.docling.parse(file_path, file_type)

        return comparison

    def _parse_native(self, file_path: str, file_type: str) -> ParseResult:
        """用 Enclave native parser 解析。"""
        import time
        t0 = time.time()

        try:
            from app.services.document_parser import DocumentParser
            text, metadata, artifact = DocumentParser.parse(file_path, file_type)

            return ParseResult(
                text=text or "",
                pages=metadata.get("pages", []),
                tables=metadata.get("tables", []),
                metadata=metadata,
                provider="native",
                elapsed_seconds=time.time() - t0,
            )
        except Exception as exc:
            return ParseResult(
                error=str(exc),
                provider="native",
                elapsed_seconds=time.time() - t0,
            )

    def run_corpus_ablation(
        self,
        file_paths: List[str],
        file_types: Optional[List[str]] = None,
    ) -> List[AblationComparison]:
        """對整個 corpus 跑 ablation。

        Args:
            file_paths: 檔案路徑列表
            file_types: 對應的檔案類型列表（可選）

        Returns:
            每個檔案的 AblationComparison 列表
        """
        results = []
        for i, fp in enumerate(file_paths):
            ft = file_types[i] if file_types and i < len(file_types) else ""
            comparison = self.run_ablation(fp, ft)
            results.append(comparison)
            winner, reason = comparison.get_winner()
            logger.info(f"Ablation {fp}: winner={winner} ({reason})")

        return results


# ── 單例 ──

_runner: Optional[ParserAblationRunner] = None


def get_parser_ablation_runner() -> ParserAblationRunner:
    global _runner
    if _runner is None:
        _runner = ParserAblationRunner()
    return _runner