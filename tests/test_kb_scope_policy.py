import uuid

from sqlalchemy.orm import sessionmaker

from app.core.authorization import AuthorizationContext
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseRevision
from app.models.tenant import Tenant
from app.services.kb_scope_policy import resolve_kb_revision_scope


def test_tenant_without_active_revision_is_explicitly_fail_closed(test_engine):
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name=f"no-active-{uuid.uuid4().hex}", status="active")
        kb = KnowledgeBase(
            id=uuid.uuid4(), tenant_id=tenant.id, name="Candidate only", status="active"
        )
        db.add_all([tenant, kb])
        db.flush()
        db.add(
            KnowledgeBaseRevision(
                kb_id=kb.id,
                revision=1,
                status="shadow",
                manifest_json={},
            )
        )
        db.flush()
        authz = AuthorizationContext(
            tenant_id=tenant.id,
            subject_id=uuid.uuid4(),
            role_ids=["employee"],
        )

        scope = resolve_kb_revision_scope(authz=authz, requested=None, db=db)

        assert scope == {"kb_revision_ids": []}
    finally:
        db.rollback()
        db.close()
