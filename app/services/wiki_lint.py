"""
P2-3：Wiki Semantic Lint — 借鑑 OpenKB linter.py。

稽核文件 §7.4：
- 借 OpenKB compiler prompt／concept planning／semantic lint／Skill evaluator
- 不整包導入 OpenKB

Semantic lint 檢查項目：
1. 空洞內容（無實質資訊的頁面）
2. 斷裂引用（引用了不存在的來源）
3. 過時內容（引用的文件已 tombstoned）
4. 結構缺失（缺少必要段落：概述、步驟、注意事項）
5. 衝突標記（與 SOP 衝突但未標註）
6. 格式問題（Markdown 格式錯誤）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LintSeverity(str, Enum):
    """Lint 嚴重程度。"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LintRule(str, Enum):
    """Lint 規則。"""
    EMPTY_CONTENT = "empty_content"
    BROKEN_REFERENCE = "broken_reference"
    STALE_REFERENCE = "stale_reference"
    MISSING_SECTION = "missing_section"
    UNMARKED_CONFLICT = "unmarked_conflict"
    FORMAT_ERROR = "format_error"
    DUPLICATE_CONTENT = "duplicate_content"


@dataclass
class LintIssue:
    """Lint 問題。"""
    rule: LintRule
    severity: LintSeverity
    message: str
    location: str = ""  # 頁面/段落位置
    suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule.value,
            "severity": self.severity.value,
            "message": self.message,
            "location": self.location,
            "suggestion": self.suggestion,
        }


@dataclass
class LintReport:
    """Lint 報告。"""
    page_id: str = ""
    page_title: str = ""
    issues: List[LintIssue] = field(default_factory=list)
    passed: bool = True

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == LintSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == LintSeverity.WARNING)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_id": self.page_id,
            "page_title": self.page_title,
            "issues": [i.to_dict() for i in self.issues],
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }


class WikiLinter:
    """Wiki Semantic Linter。

    借鑑 OpenKB linter.py 的檢查模式，但原生實作。
    """

    # 必要段落（製造業 Wiki）
    REQUIRED_SECTIONS = ["概述", "步驟", "注意事項"]

    def lint(
        self,
        page_id: str,
        page_title: str,
        content: str,
        source_documents: Optional[List[Dict[str, Any]]] = None,
        known_conflicts: Optional[List[Dict[str, Any]]] = None,
    ) -> LintReport:
        """執行 semantic lint。

        Args:
            page_id: Wiki 頁面 ID
            page_title: 頁面標題
            content: Markdown 內容
            source_documents: 引用的來源文件列表（含 id, status, tombstoned_at）
            known_conflicts: 已知的 SOP 衝突列表

        Returns:
            LintReport
        """
        report = LintReport(page_id=page_id, page_title=page_title)
        source_documents = source_documents or []
        known_conflicts = known_conflicts or []

        # 1. 空洞內容
        self._check_empty_content(content, report)

        # 2. 結構缺失
        self._check_missing_sections(content, report)

        # 3. 斷裂引用
        self._check_broken_references(content, source_documents, report)

        # 4. 過時內容
        self._check_stale_references(content, source_documents, report)

        # 5. 未標註衝突
        self._check_unmarked_conflicts(content, known_conflicts, report)

        # 6. 格式問題
        self._check_format_errors(content, report)

        # 7. 重複內容
        self._check_duplicate_content(content, report)

        report.passed = report.error_count == 0
        return report

    def _check_empty_content(self, content: str, report: LintReport) -> None:
        """檢查空洞內容。"""
        # 去除 Markdown 標記後檢查實質內容
        stripped = re.sub(r'[#*\-|`\[\]()]', '', content).strip()
        if len(stripped) < 50:
            report.issues.append(LintIssue(
                rule=LintRule.EMPTY_CONTENT,
                severity=LintSeverity.WARNING,
                message=f"頁面內容過短（{len(stripped)} 字元），可能缺乏實質資訊",
                suggestion="補充概述、步驟、注意事項等必要段落",
            ))

    def _check_missing_sections(self, content: str, report: LintReport) -> None:
        """檢查結構缺失。"""
        for section in self.REQUIRED_SECTIONS:
            # 檢查是否有對應的標題（## 概述、## 步驟 等）
            pattern = rf'^#+\s*{section}'
            if not re.search(pattern, content, re.MULTILINE):
                report.issues.append(LintIssue(
                    rule=LintRule.MISSING_SECTION,
                    severity=LintSeverity.WARNING,
                    message=f"缺少必要段落: {section}",
                    suggestion=f"新增 ## {section} 段落",
                ))

    def _check_broken_references(
        self,
        content: str,
        source_documents: List[Dict[str, Any]],
        report: LintReport,
    ) -> None:
        """檢查斷裂引用。"""
        # 嚴格格式：[來源:doc-001] 或 [source:doc-001]，避免誤匹配一般文字
        ref_pattern = r'\[(?:來源|source)[:\s]*([a-zA-Z0-9\-]+)\]'
        refs = re.findall(ref_pattern, content, re.IGNORECASE)

        source_ids = {str(d.get("id", "")) for d in source_documents}

        for ref in refs:
            if ref not in source_ids:
                report.issues.append(LintIssue(
                    rule=LintRule.BROKEN_REFERENCE,
                    severity=LintSeverity.ERROR,
                    message=f"引用了不存在的來源: {ref}",
                    location=ref,
                    suggestion="移除斷裂引用或重新關聯正確的來源文件",
                ))

    def _check_stale_references(
        self,
        content: str,
        source_documents: List[Dict[str, Any]],
        report: LintReport,
    ) -> None:
        """檢查過時引用（來源已 tombstoned）。"""
        for doc in source_documents:
            if doc.get("tombstoned_at") or doc.get("status") == "tombstoned":
                doc_id = str(doc.get("id", ""))
                if doc_id and doc_id in content:
                    report.issues.append(LintIssue(
                        rule=LintRule.STALE_REFERENCE,
                        severity=LintSeverity.ERROR,
                        message=f"引用了已刪除的來源: {doc_id}",
                        location=doc_id,
                        suggestion="移除過時引用或重新關聯有效來源",
                    ))

    def _check_unmarked_conflicts(
        self,
        content: str,
        known_conflicts: List[Dict[str, Any]],
        report: LintReport,
    ) -> None:
        """檢查未標註的衝突。"""
        unresolved = [c for c in known_conflicts if not c.get("resolved")]
        if unresolved:
            # 檢查內容是否有衝突標記
            conflict_marker = "⚠️" in content or "衝突" in content or "conflict" in content.lower()
            if not conflict_marker:
                report.issues.append(LintIssue(
                    rule=LintRule.UNMARKED_CONFLICT,
                    severity=LintSeverity.WARNING,
                    message=f"有 {len(unresolved)} 個未解決的 SOP 衝突但頁面未標註",
                    suggestion="在頁面中加入衝突標記並說明 SOP 優先",
                ))

    def _check_format_errors(self, content: str, report: LintReport) -> None:
        """檢查格式問題。"""
        # 檢查未關閉的程式碼區塊
        code_blocks = content.count("```")
        if code_blocks % 2 != 0:
            report.issues.append(LintIssue(
                rule=LintRule.FORMAT_ERROR,
                severity=LintSeverity.ERROR,
                message="程式碼區塊未關閉（``` 不成對）",
                suggestion="補上遺漏的 ``` 結束標記",
            ))

        # 檢查未關閉的連結
        open_links = len(re.findall(r'\[([^\]]+)\]\(', content))
        close_links = content.count("](")
        if open_links != close_links:
            report.issues.append(LintIssue(
                rule=LintRule.FORMAT_ERROR,
                severity=LintSeverity.WARNING,
                message=f"Markdown 連結可能不完整（開頭 {open_links}，結尾 {close_links}）",
                suggestion="檢查所有 [text](url) 連結是否完整",
            ))

    def _check_duplicate_content(self, content: str, report: LintReport) -> None:
        """檢查重複內容。"""
        # 檢查連續重複的段落
        lines = content.split("\n")
        for i in range(len(lines) - 1):
            if (
                lines[i].strip()
                and len(lines[i].strip()) > 20
                and lines[i].strip() == lines[i + 1].strip()
            ):
                report.issues.append(LintIssue(
                    rule=LintRule.DUPLICATE_CONTENT,
                    severity=LintSeverity.INFO,
                    message=f"第 {i+1}-{i+2} 行內容重複",
                    location=f"line {i+1}",
                    suggestion="移除重複行",
                ))


# ── 單例 ──

_linter: Optional[WikiLinter] = None


def get_wiki_linter() -> WikiLinter:
    global _linter
    if _linter is None:
        _linter = WikiLinter()
    return _linter