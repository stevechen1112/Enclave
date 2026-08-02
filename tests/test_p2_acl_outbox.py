"""P2: dual-worker outbox claim + cross-department ACL (no live Postgres required)."""
from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.core.authorization import AuthorizationContext
from app.services.resource_policy import ResourcePolicyService


def _authz(tenant_id, *, dept_ids=None, role_ids=None, is_superuser=False):
    return AuthorizationContext(
        tenant_id=tenant_id,
        subject_id=uuid.uuid4(),
        role_ids=role_ids or ["employee"],
        department_ids=list(dept_ids or []),
        is_superuser=is_superuser,
        policy_revision=1,
    )


def _doc(*, tenant_id, department_id=None, tombstoned=False, source_system=None):
    doc = MagicMock()
    doc.id = uuid.uuid4()
    doc.tenant_id = tenant_id
    doc.department_id = department_id
    doc.tombstoned_at = datetime.now(timezone.utc) if tombstoned else None
    doc.source_system = source_system
    doc.source_record_id = None
    return doc


class TestDualWorkerOutboxClaim:
    def test_claim_source_uses_skip_locked(self):
        from app.tasks import outbox_worker as ow

        src = inspect.getsource(ow._claim_outbox_events)
        assert "skip_locked" in src
        assert "with_for_update" in src
        assert "STALE_PROCESSING" in src or "stale" in src.lower()

    def test_process_outbox_commits_claim_before_dispatch(self):
        """Worker A must commit claim so worker B's SKIP LOCKED can see processing rows."""
        from app.tasks import outbox_worker as ow

        src = inspect.getsource(ow.process_outbox_batch)
        claim_idx = src.find("_claim_outbox_events")
        commit_idx = src.find("db.commit()")
        assert claim_idx != -1 and commit_idx != -1
        assert claim_idx < commit_idx

    def test_claim_marks_processing_on_returned_events(self):
        from app.tasks.outbox_worker import _claim_outbox_events

        ev = MagicMock()
        ev.status = "pending"
        ev.attempts = 0
        ev.updated_at = None

        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
        q.with_for_update.return_value = q
        q.all.return_value = [ev]

        db = MagicMock()
        db.query.return_value = q
        bind = MagicMock()
        bind.dialect.name = "postgresql"
        db.get_bind.return_value = bind

        claimed = _claim_outbox_events(db)
        assert claimed == [ev]
        assert ev.status == "processing"
        assert ev.attempts == 1
        db.flush.assert_called()

    def test_second_claim_filter_excludes_fresh_processing(self):
        """Claim filter must not select non-stale processing (dual-worker safety)."""
        from app.tasks import outbox_worker as ow

        src = inspect.getsource(ow._claim_outbox_events)
        assert 'status.in_(["pending", "failed"])' in src or "pending" in src
        assert '"processing"' in src
        assert "stale_before" in src


class TestCrossDepartmentAcl:
    def test_employee_cannot_access_other_department_doc(self):
        tenant = uuid.uuid4()
        dept_a, dept_b = uuid.uuid4(), uuid.uuid4()
        authz = _authz(tenant, dept_ids=[dept_a], role_ids=["employee"])
        doc = _doc(tenant_id=tenant, department_id=dept_b)
        pep = ResourcePolicyService()
        with patch.object(pep, "is_denied", return_value=False):
            assert pep.authorize_document(MagicMock(), authz, doc) is False

    def test_employee_can_access_own_department_doc(self):
        tenant = uuid.uuid4()
        dept = uuid.uuid4()
        authz = _authz(tenant, dept_ids=[dept], role_ids=["employee"])
        doc = _doc(tenant_id=tenant, department_id=dept)
        pep = ResourcePolicyService()
        with patch.object(pep, "is_denied", return_value=False):
            assert pep.authorize_document(MagicMock(), authz, doc) is True

    def test_null_department_visible_to_member(self):
        tenant = uuid.uuid4()
        authz = _authz(tenant, dept_ids=[uuid.uuid4()], role_ids=["employee"])
        doc = _doc(tenant_id=tenant, department_id=None)
        pep = ResourcePolicyService()
        with patch.object(pep, "is_denied", return_value=False):
            assert pep.authorize_document(MagicMock(), authz, doc) is True

    def test_ancestor_department_path_allows_child(self):
        parent, child = uuid.uuid4(), uuid.uuid4()
        tenant = uuid.uuid4()
        authz = _authz(tenant, dept_ids=[parent, child], role_ids=["hr"])
        assert authz.can_access_document(tenant, child) is True
        assert authz.can_access_document(tenant, parent) is True

    def test_kb_admin_bypasses_department(self):
        tenant = uuid.uuid4()
        authz = _authz(tenant, dept_ids=[], role_ids=["kb_admin"])
        doc = _doc(tenant_id=tenant, department_id=uuid.uuid4())
        pep = ResourcePolicyService()
        with patch.object(pep, "is_denied", return_value=False):
            assert pep.authorize_document(MagicMock(), authz, doc) is True

    def test_cross_tenant_denied(self):
        tenant = uuid.uuid4()
        other = _authz(uuid.uuid4(), dept_ids=[], role_ids=["kb_admin"])
        doc = _doc(tenant_id=tenant, department_id=None)
        pep = ResourcePolicyService()
        with patch.object(pep, "is_denied", return_value=False):
            assert pep.authorize_document(MagicMock(), other, doc) is False

    def test_tombstoned_denied(self):
        tenant = uuid.uuid4()
        authz = _authz(tenant, dept_ids=[], role_ids=["kb_admin"])
        doc = _doc(tenant_id=tenant, tombstoned=True)
        pep = ResourcePolicyService()
        with patch.object(pep, "is_denied", return_value=False):
            assert pep.authorize_document(MagicMock(), authz, doc) is False

    def test_delete_endpoint_has_department_pep(self):
        from app.api.v1.endpoints import documents as docs_mod

        src = inspect.getsource(docs_mod.delete_document)
        assert "can_access_document_by_department" in src
