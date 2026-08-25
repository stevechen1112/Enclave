"""Persistent, incrementally maintained lexical index."""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from app.models.document import Document, DocumentChunk
from app.models.knowledge_engine import LexicalIndexEntry

INDEX_VERSION = "lexical-1"


def tokenize(text: str) -> list[str]:
    try:
        import jieba
        tokens = jieba.lcut((text or "").casefold())
    except ImportError:
        tokens = re.findall(r"[\w\u3400-\u9fff]+", (text or "").casefold())
    return sorted({t.strip() for t in tokens if len(t.strip()) >= 2})


def upsert_chunks(db, chunks: Iterable[DocumentChunk], document: Document) -> int:
    count = 0
    for chunk in chunks:
        tokens = tokenize(chunk.text or "")
        digest = hashlib.sha256((chunk.text or "").encode("utf-8", errors="replace")).hexdigest()
        row = db.query(LexicalIndexEntry).filter(LexicalIndexEntry.chunk_id == chunk.id).first()
        values = {"tenant_id": chunk.tenant_id, "document_id": chunk.document_id,
                  "document_revision": int(chunk.document_revision or document.version or 1), "tokens": tokens,
                  "token_count": len(tokens), "content_hash": digest, "index_version": INDEX_VERSION}
        if row is None:
            row = LexicalIndexEntry(chunk_id=chunk.id, **values); db.add(row)
        else:
            for key, value in values.items(): setattr(row, key, value)
        count += 1
    db.flush()
    return count


def search(db, *, tenant_id, query: str, top_k: int, base_query):
    qtokens = tokenize(query)
    if not qtokens:
        return []
    rows = (base_query.add_entity(LexicalIndexEntry).join(LexicalIndexEntry, LexicalIndexEntry.chunk_id == DocumentChunk.id)
            .filter(LexicalIndexEntry.tenant_id == tenant_id, LexicalIndexEntry.tokens.op("&&")(qtokens))
            .limit(max(top_k * 10, 50)).all())
    wanted = set(qtokens)
    scored = [(chunk, len(wanted.intersection(entry.tokens or [])) / max(len(wanted), 1)) for chunk, entry in rows]
    return sorted(scored, key=lambda pair: pair[1], reverse=True)[:top_k]
