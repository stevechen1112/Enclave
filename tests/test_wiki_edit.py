"""Wiki admin manual edit — service and endpoint behavior."""
from __future__ import annotations

import uuid

import pytest

from app.services.wiki_compiler import WikiCompiler


def _seed_page(db, *, status="published", tombstoned=False):
    import app.models  # noqa: F401
    from app.models.tenant import Tenant
    from app.models.knowledge_base import KnowledgeBase
    from app.models.wiki import WikiPage, WikiRevision
    from datetime import datetime, timezone

    tenant = Tenant(id=uuid.uuid4(), name="WikiEdit", plan="free", status="active")
    db.add(tenant)
    db.flush()
    kb = KnowledgeBase(id=uuid.uuid4(), tenant_id=tenant.id, name="kb-edit", status="active")
    db.add(kb)
    db.flush()
    page = WikiPage(
        id=uuid.uuid4(), tenant_id=tenant.id, kb_id=kb.id,
        slug="summary-edit", title="原始標題", page_type="summary",
        status=status, source_document_ids=[], active_revision=1,
    )
    if tombstoned:
        page.status = "tombstoned"
        page.tombstoned_at = datetime.now(timezone.utc)
    db.add(page)
    db.flush()
    rev = WikiRevision(
        wiki_page_id=page.id, revision=1, content="# 原始內容",
        content_hash="orig123",
        citation_map=[{"document_id": str(uuid.uuid4()), "revision": 1}],
        compile_job_id="wiki-orig",
    )
    db.add(rev)
    db.commit()
    return tenant, page


@pytest.fixture
def db_session(test_engine):
    import app.models  # noqa: F401
    from app.db.base_class import Base
    from sqlalchemy.orm import sessionmaker

    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    db = Session()
    yield db
    db.close()


class TestEditPageService:
    def test_content_change_creates_new_revision_and_keeps_citations(self, db_session):
        from app.models.wiki import WikiRevision

        _, page = _seed_page(db_session)
        result = WikiCompiler().edit_page(
            db_session, page, content="# 修正後內容", editor_id="admin-1",
        )
        assert result.active_revision == 2
        revs = (
            db_session.query(WikiRevision)
            .filter(WikiRevision.wiki_page_id == page.id)
            .order_by(WikiRevision.revision)
            .all()
        )
        assert len(revs) == 2
        assert revs[0].content == "# 原始內容"  # 歷史不覆寫
        assert revs[1].content == "# 修正後內容"
        assert revs[1].citation_map == revs[0].citation_map  # 引用沿用
        assert revs[1].compile_job_id == "manual-edit-admin-1"

    def test_title_only_edit_does_not_create_revision(self, db_session):
        from app.models.wiki import WikiRevision

        _, page = _seed_page(db_session)
        result = WikiCompiler().edit_page(db_session, page, title="新標題")
        assert result.title == "新標題"
        assert result.active_revision == 1
        count = db_session.query(WikiRevision).filter(WikiRevision.wiki_page_id == page.id).count()
        assert count == 1

    def test_identical_content_does_not_create_revision(self, db_session):
        _, page = _seed_page(db_session)
        result = WikiCompiler().edit_page(db_session, page, content="# 原始內容")
        assert result.active_revision == 1

    def test_draft_page_becomes_published_on_edit(self, db_session):
        _, page = _seed_page(db_session, status="draft")
        result = WikiCompiler().edit_page(db_session, page, content="新內容")
        assert result.status == "published"


class TestEditPageEndpoint:
    def _call(self, db, page, user, body):
        from fastapi import Response
        from app.api.v1.endpoints.wiki import edit_wiki_page, WikiEditRequest

        return edit_wiki_page(
            page_id=page.id, body=WikiEditRequest(**body),
            response=Response(), db=db, current_user=user,
        )

    def test_admin_edit_via_endpoint(self, db_session):
        tenant, page = _seed_page(db_session)
        admin = type("U", (), {
            "id": uuid.uuid4(), "tenant_id": tenant.id, "role": "admin",
        })()
        out = self._call(db_session, page, admin, {"title": "端點標題", "content": "端點內容"})
        assert out.title == "端點標題"
        assert out.active_revision == 2

    def test_cross_tenant_edit_returns_404(self, db_session):
        _, page = _seed_page(db_session)
        outsider = type("U", (), {
            "id": uuid.uuid4(), "tenant_id": uuid.uuid4(), "role": "admin",
        })()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            self._call(db_session, page, outsider, {"title": "x"})
        assert ei.value.status_code == 404

    def test_tombstoned_page_not_editable(self, db_session):
        tenant, page = _seed_page(db_session, tombstoned=True)
        admin = type("U", (), {
            "id": uuid.uuid4(), "tenant_id": tenant.id, "role": "admin",
        })()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            self._call(db_session, page, admin, {"content": "x"})
        assert ei.value.status_code == 404

    def test_empty_body_returns_400(self, db_session):
        tenant, page = _seed_page(db_session)
        admin = type("U", (), {
            "id": uuid.uuid4(), "tenant_id": tenant.id, "role": "admin",
        })()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            self._call(db_session, page, admin, {})
        assert ei.value.status_code == 400
