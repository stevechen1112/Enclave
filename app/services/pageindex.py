"""
P2-4：PageIndex — 長文件頁級索引樹。

稽核文件 §7.4 P2、§11.5：
- 只適用長設備手冊、20 頁以上 manual
- 預設 OFF
- 寫 DocumentArtifact(pageindex_tree)
- 不取代 canonical index
- 通過 ablation 才進 fan-out

借鑑 OpenKB indexer.py 的 PageIndex tree 結構：
- pageindex_threshold: 20
- 長 PDF 走 PageIndex tree
- query 時按頁取內容

Enclave 原生實作，利用 DocumentChunk.metadata_json["page"] + parent_chunk_id。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PageNode:
    """頁節點。"""
    page_number: int
    chunk_ids: List[str] = field(default_factory=list)
    text_preview: str = ""  # 頁首 N 字元
    section_title: str = ""
    children: List["PageNode"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_number": self.page_number,
            "chunk_ids": self.chunk_ids,
            "text_preview": self.text_preview[:200],
            "section_title": self.section_title,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class PageIndexTree:
    """頁索引樹。"""
    document_id: str
    total_pages: int = 0
    pages: List[PageNode] = field(default_factory=list)
    # 頁範圍索引（page_start, page_end → page_numbers）
    section_ranges: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "total_pages": self.total_pages,
            "pages": [p.to_dict() for p in self.pages],
            "section_ranges": self.section_ranges,
            "schema": 1,
        }


class PageIndexBuilder:
    """PageIndex 建立器。"""

    def build_from_chunks(
        self,
        document_id: str,
        chunks: List[Dict[str, Any]],
        threshold: int = 20,
    ) -> Optional[PageIndexTree]:
        """從 chunk 列表建立 PageIndex tree。

        Args:
            document_id: 文件 ID
            chunks: chunk dict 列表，每個含 chunk_index, metadata.page, text 等
            threshold: 頁數門檻（低於此不建 tree）

        Returns:
            PageIndexTree 或 None（頁數不足）
        """
        # 收集所有頁碼
        page_chunks: Dict[int, List[Dict[str, Any]]] = {}
        for chunk in chunks:
            page = chunk.get("metadata", {}).get("page")
            if page is None:
                continue
            page = int(page)
            if page not in page_chunks:
                page_chunks[page] = []
            page_chunks[page].append(chunk)

        total_pages = len(page_chunks)
        max_page_number = max(page_chunks.keys()) if page_chunks else 0

        # 頁數不足門檻，不建 tree
        if total_pages < threshold:
            logger.info(
                f"PageIndex skip: document {document_id} has {total_pages} pages "
                f"(threshold={threshold})"
            )
            return None

        # 建立頁節點
        pages: List[PageNode] = []
        for page_num in sorted(page_chunks.keys()):
            page_data = page_chunks[page_num]
            # 取頁首文字預覽
            first_chunk = page_data[0] if page_data else {}
            text = first_chunk.get("text") or first_chunk.get("content") or ""
            pages.append(PageNode(
                page_number=page_num,
                chunk_ids=[str(c.get("id", "")) for c in page_data],
                text_preview=text[:200],
                section_title=self._extract_section_title(text),
            ))

        # 偵測 section 範圍
        section_ranges = self._detect_section_ranges(pages)

        tree = PageIndexTree(
            document_id=document_id,
            total_pages=total_pages,
            pages=pages,
            section_ranges=section_ranges,
        )

        logger.info(
            f"PageIndex built: document {document_id}, "
            f"{total_pages} pages (max page #{max_page_number}), {len(section_ranges)} sections"
        )
        return tree

    def _extract_section_title(self, text: str) -> str:
        """從頁首文字提取 section 標題。"""
        import re
        # 檢查 Markdown 標題
        match = re.match(r'^#+\s*(.+)', text)
        if match:
            return match.group(1).strip()[:100]
        # 檢查第一行
        first_line = text.split("\n")[0].strip()
        if first_line and len(first_line) < 100:
            return first_line
        return ""

    def _detect_section_ranges(self, pages: List[PageNode]) -> List[Dict[str, Any]]:
        """偵測 section 範圍（連續頁有相同 section_title）。"""
        ranges: List[Dict[str, Any]] = []
        if not pages:
            return ranges

        current_title = pages[0].section_title
        current_start = pages[0].page_number

        for i in range(1, len(pages)):
            # 空標題的頁歸入當前 section（不觸發新 section）
            if pages[i].section_title and pages[i].section_title != current_title:
                # 新 section 開始
                ranges.append({
                    "title": current_title,
                    "page_start": current_start,
                    "page_end": pages[i].page_number - 1,
                })
                current_title = pages[i].section_title
                current_start = pages[i].page_number

        # 最後一個 section
        ranges.append({
            "title": current_title,
            "page_start": current_start,
            "page_end": pages[-1].page_number,
        })

        return ranges


class PageIndexRetriever:
    """PageIndex 檢索器 — 按頁範圍取內容。"""

    def get_pages_for_query(
        self,
        tree: PageIndexTree,
        query: str,
        max_pages: int = 5,
    ) -> List[int]:
        """根據查詢決定要取哪些頁。

        策略：
        1. 若 query 含頁碼（「第 5 頁」），直接取該頁
        2. 若 query 含 section 標題關鍵字，取對應 section 範圍
        3. 否則取前 max_pages 頁

        Args:
            tree: PageIndexTree
            query: 查詢字串
            max_pages: 最多取幾頁

        Returns:
            頁碼列表
        """
        import re

        # 1. 頁碼直接取
        page_match = re.search(r'第\s*(\d+)\s*頁', query)
        if page_match:
            page_num = int(page_match.group(1))
            if 1 <= page_num <= tree.total_pages:
                return [page_num]

        # 2. section 標題關鍵字
        for section in tree.section_ranges:
            title = section.get("title", "")
            if title and title in query:
                start = section["page_start"]
                end = section["page_end"]
                pages = list(range(start, end + 1))
                return pages[:max_pages]

        # 3. 預設取前 N 頁
        return [p.page_number for p in tree.pages[:max_pages]]

    def get_chunks_for_pages(
        self,
        tree: PageIndexTree,
        page_numbers: List[int],
    ) -> List[str]:
        """取得指定頁的 chunk IDs。"""
        chunk_ids: List[str] = []
        page_set = set(page_numbers)
        for page in tree.pages:
            if page.page_number in page_set:
                chunk_ids.extend(page.chunk_ids)
        return chunk_ids


# ── 單例 ──

_builder: Optional[PageIndexBuilder] = None
_retriever: Optional[PageIndexRetriever] = None


def get_pageindex_builder() -> PageIndexBuilder:
    global _builder
    if _builder is None:
        _builder = PageIndexBuilder()
    return _builder


def get_pageindex_retriever() -> PageIndexRetriever:
    global _retriever
    if _retriever is None:
        _retriever = PageIndexRetriever()
    return _retriever