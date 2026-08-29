"""Phase 3 — External principal mapping for source ACL."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.connector import ExternalPrincipal, SourceAclEntry

logger = logging.getLogger(__name__)


class ExternalPrincipalService:
    def map_principal(
        self,
        db: Session,
        tenant_id: UUID,
        provider: str,
        external_id: str,
        principal_type: str,
        mapped_subject_id: Optional[UUID] = None,
        mapped_subject_type: Optional[str] = None,
    ) -> ExternalPrincipal:
        row = (
            db.query(ExternalPrincipal)
            .filter(
                ExternalPrincipal.tenant_id == tenant_id,
                ExternalPrincipal.provider == provider,
                ExternalPrincipal.external_id == external_id,
            )
            .first()
        )
        if row:
            row.mapped_subject_id = mapped_subject_id
            row.mapped_subject_type = mapped_subject_type
            row.principal_type = principal_type
            db.flush()
            return row

        row = ExternalPrincipal(
            tenant_id=tenant_id,
            provider=provider,
            external_id=external_id,
            principal_type=principal_type,
            mapped_subject_id=mapped_subject_id,
            mapped_subject_type=mapped_subject_type,
        )
        db.add(row)
        db.flush()
        return row

    def get_principal_ids_for_subject(
        self, db: Session, tenant_id: UUID, subject_id: UUID,
    ) -> List[UUID]:
        rows = (
            db.query(ExternalPrincipal)
            .filter(
                ExternalPrincipal.tenant_id == tenant_id,
                ExternalPrincipal.mapped_subject_id == subject_id,
            )
            .all()
        )
        return [r.id for r in rows]

    def apply_acl_entries(
        self,
        db: Session,
        tenant_id: UUID,
        entries: List[dict],
    ) -> int:
        """Upsert source ACL projection from connector sync."""
        count = 0
        for entry in entries:
            principal = self.map_principal(
                db,
                tenant_id=tenant_id,
                provider=entry.get("provider", "pipeshub"),
                external_id=entry["principal_external_id"],
                principal_type=entry.get("principal_type", "user"),
                mapped_subject_id=entry.get("mapped_subject_id"),
                mapped_subject_type=entry.get("mapped_subject_type"),
            )
            source_record_id = entry["source_record_id"]
            existing = (
                db.query(SourceAclEntry)
                .filter(
                    SourceAclEntry.tenant_id == tenant_id,
                    SourceAclEntry.source_record_id == source_record_id,
                    SourceAclEntry.principal_id == principal.id,
                    SourceAclEntry.permission == entry.get("permission", "read"),
                )
                .first()
            )
            if existing:
                existing.effect = entry.get("effect", "allow")
                existing.inherited = entry.get("inherited", False)
                existing.revision = entry.get("revision", existing.revision + 1)
            else:
                db.add(
                    SourceAclEntry(
                        tenant_id=tenant_id,
                        source_record_id=source_record_id,
                        principal_id=principal.id,
                        permission=entry.get("permission", "read"),
                        effect=entry.get("effect", "allow"),
                        inherited=entry.get("inherited", False),
                        revision=entry.get("revision", 1),
                    )
                )
            count += 1
        db.flush()
        return count

    def replace_acl_snapshot(
        self,
        db: Session,
        tenant_id: UUID,
        entries: List[dict],
        *,
        source_record_ids: set[str],
    ) -> dict[str, int]:
        """Replace ACLs for a complete source snapshot without widening access.

        Omitted entries are revoked only for source records explicitly included
        in this complete snapshot. An empty/incomplete provider response cannot
        erase or broaden unrelated ACL state.
        """

        grouped: dict[str, list[dict]] = defaultdict(list)
        for entry in entries:
            record_id = str(entry.get("source_record_id") or "")
            if record_id in source_record_ids:
                grouped[record_id].append(entry)

        scoped_entries = [
            entry
            for entry in entries
            if str(entry.get("source_record_id") or "") in source_record_ids
        ]
        applied = self.apply_acl_entries(db, tenant_id, scoped_entries)
        retained: dict[str, set[tuple[UUID, str]]] = defaultdict(set)
        for record_id, record_entries in grouped.items():
            for entry in record_entries:
                principal = (
                    db.query(ExternalPrincipal)
                    .filter(
                        ExternalPrincipal.tenant_id == tenant_id,
                        ExternalPrincipal.provider == entry.get("provider", "pipeshub"),
                        ExternalPrincipal.external_id == entry["principal_external_id"],
                    )
                    .first()
                )
                if principal:
                    retained[record_id].add(
                        (principal.id, entry.get("permission", "read"))
                    )

        revoked = 0
        existing = (
            db.query(SourceAclEntry)
            .filter(
                SourceAclEntry.tenant_id == tenant_id,
                SourceAclEntry.source_record_id.in_(source_record_ids),
            )
            .all()
            if source_record_ids
            else []
        )
        for row in existing:
            if (row.principal_id, row.permission) not in retained[row.source_record_id]:
                db.delete(row)
                revoked += 1
        db.flush()
        return {"applied": applied, "revoked": revoked}

    def sample_acl_for_source(
        self, db: Session, tenant_id: UUID, source_record_id: str, limit: int = 20,
    ) -> List[dict]:
        rows = (
            db.query(SourceAclEntry)
            .filter(
                SourceAclEntry.tenant_id == tenant_id,
                SourceAclEntry.source_record_id == source_record_id,
            )
            .limit(limit)
            .all()
        )
        return [
            {
                "principal_id": str(r.principal_id),
                "permission": r.permission,
                "effect": r.effect,
                "inherited": r.inherited,
                "revision": r.revision,
            }
            for r in rows
        ]
