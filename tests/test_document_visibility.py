import uuid

from sqlalchemy.orm import sessionmaker

from app.core.authorization import AuthorizationContext
from app.models.connector import ExternalPrincipal, SourceAclEntry
from app.models.document import Document
from app.models.tenant import Tenant
from app.services.document_visibility import apply_document_visibility


def test_document_listing_pep_enforces_source_allow_and_deny(test_engine):
    db = sessionmaker(bind=test_engine)()
    try:
        tenant = Tenant(id=uuid.uuid4(), name=f"acl-{uuid.uuid4().hex}", status="active")
        subject_id = uuid.uuid4()
        local = Document(
            tenant_id=tenant.id,
            filename="local.txt",
            status="completed",
            source_type="file",
        )
        allowed = Document(
            tenant_id=tenant.id,
            filename="allowed.txt",
            status="completed",
            source_type="connector",
            source_system="sharepoint",
            source_record_id="allowed-record",
        )
        denied = Document(
            tenant_id=tenant.id,
            filename="denied.txt",
            status="completed",
            source_type="connector",
            source_system="sharepoint",
            source_record_id="denied-record",
        )
        unmapped = Document(
            tenant_id=tenant.id,
            filename="unmapped.txt",
            status="completed",
            source_type="connector",
            source_system="sharepoint",
            source_record_id="unmapped-record",
        )
        db.add_all([tenant, local, allowed, denied, unmapped])
        db.flush()
        principal = ExternalPrincipal(
            tenant_id=tenant.id,
            provider="sharepoint",
            external_id="user-1",
            principal_type="user",
            mapped_subject_id=subject_id,
            mapped_subject_type="user",
        )
        db.add(principal)
        db.flush()
        db.add_all([
            SourceAclEntry(
                tenant_id=tenant.id,
                source_record_id="allowed-record",
                principal_id=principal.id,
                permission="read",
                effect="allow",
            ),
            SourceAclEntry(
                tenant_id=tenant.id,
                source_record_id="denied-record",
                principal_id=principal.id,
                permission="read",
                effect="allow",
            ),
            SourceAclEntry(
                tenant_id=tenant.id,
                source_record_id="denied-record",
                principal_id=principal.id,
                permission="read",
                effect="deny",
            ),
        ])
        db.flush()
        authz = AuthorizationContext(
            tenant_id=tenant.id,
            subject_id=subject_id,
            role_ids=["employee"],
        )

        rows = apply_document_visibility(
            db.query(Document), authz=authz, db=db, require_completed=False
        ).all()

        assert {row.filename for row in rows} == {"local.txt", "allowed.txt"}
    finally:
        db.rollback()
        db.close()
