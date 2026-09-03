from __future__ import annotations

from unittest.mock import Mock

from sqlalchemy.dialects import postgresql

from app.models.document import Document
from app.services import kb_retrieval


def test_first_party_web_input_is_not_treated_as_an_external_connector() -> None:
    retriever = kb_retrieval.KnowledgeBaseRetriever.__new__(
        kb_retrieval.KnowledgeBaseRetriever
    )
    principals = Mock()
    principals.filter.return_value.all.return_value = []
    db = Mock()
    db.query.return_value = principals
    source_query = Mock()
    authz = Mock()
    authz.has_kb_admin = False

    retriever._apply_source_acl_filter(source_query, Mock(), authz, db)

    criterion = source_query.filter.call_args.args[0]
    sql = str(
        criterion.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "documents.source_type != 'connector'" in sql
    assert "documents.source_system IS NULL" not in sql


def test_retrieval_cache_authenticates_to_production_redis(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeRedis:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def ping(self):
            return True

    monkeypatch.setenv("REDIS_PASSWORD", "runtime-secret")
    monkeypatch.setattr(kb_retrieval, "_HAS_REDIS", True)
    monkeypatch.setattr(kb_retrieval.redis_lib, "Redis", FakeRedis)
    monkeypatch.setattr(kb_retrieval.settings, "REDIS_HOST", "redis")
    monkeypatch.setattr(kb_retrieval.settings, "REDIS_PORT", 6379)

    client = kb_retrieval._connect_redis_cache()

    assert client is not None
    assert captured["host"] == "redis"
    assert captured["password"] == "runtime-secret"
    assert captured["db"] == 1
