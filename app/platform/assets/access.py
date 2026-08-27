"""Versioned, domain-neutral access policy for canonical source assets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

_VISIBILITIES = {"tenant", "private", "restricted"}


def _string_set(value: Any, *, field_name: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise TypeError(f"asset ACL {field_name} must be a collection")
    return frozenset(str(item).strip() for item in value if str(item).strip())


@dataclass(frozen=True)
class AssetAccessPolicy:
    """Normalized ACL snapshot stored with a SourceAsset.

    Explicit deny always wins. ``tenant`` preserves the historic Enclave
    behavior for uploads, while ``private`` and ``restricted`` require an
    owner or explicit allow match. Tenant equality and lifecycle checks are
    intentionally enforced by the canonical service, not this pure contract.
    """

    visibility: str = "tenant"
    owner_subject_id: str | None = None
    allowed_subject_ids: frozenset[str] = frozenset()
    allowed_role_ids: frozenset[str] = frozenset()
    allowed_department_ids: frozenset[str] = frozenset()
    allowed_group_ids: frozenset[str] = frozenset()
    denied_subject_ids: frozenset[str] = frozenset()
    denied_role_ids: frozenset[str] = frozenset()
    denied_department_ids: frozenset[str] = frozenset()
    denied_group_ids: frozenset[str] = frozenset()
    policy_revision: int = 1
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        visibility = str(self.visibility or "").strip().lower()
        if visibility not in _VISIBILITIES:
            raise ValueError(f"unsupported asset visibility: {visibility!r}")
        if int(self.policy_revision) < 1:
            raise ValueError("asset ACL policy_revision must be >= 1")
        object.__setattr__(self, "visibility", visibility)
        object.__setattr__(
            self,
            "owner_subject_id",
            str(self.owner_subject_id).strip() if self.owner_subject_id else None,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> AssetAccessPolicy:
        raw = dict(value or {})
        # Phase B stored ``department_id`` and video F1 stored ``uploaded_by``.
        # Preserve video's tenant-wide behavior; a legacy department assignment
        # is an explicit restriction and must continue to narrow visibility.
        legacy_department = str(raw.get("department_id") or "").strip()
        allowed_departments = list(raw.get("allowed_department_ids") or [])
        if legacy_department and legacy_department not in allowed_departments:
            allowed_departments.append(legacy_department)
        explicit_visibility = raw.get("visibility")
        visibility = (
            str(explicit_visibility).strip().lower()
            if explicit_visibility is not None
            else "restricted"
            if allowed_departments
            else "tenant"
        )
        return cls(
            visibility=visibility,
            owner_subject_id=raw.get("owner_subject_id") or raw.get("uploaded_by"),
            allowed_subject_ids=_string_set(
                raw.get("allowed_subject_ids"), field_name="allowed_subject_ids"
            ),
            allowed_role_ids=_string_set(
                raw.get("allowed_role_ids"), field_name="allowed_role_ids"
            ),
            allowed_department_ids=_string_set(
                allowed_departments, field_name="allowed_department_ids"
            ),
            allowed_group_ids=_string_set(
                raw.get("allowed_group_ids"), field_name="allowed_group_ids"
            ),
            denied_subject_ids=_string_set(
                raw.get("denied_subject_ids"), field_name="denied_subject_ids"
            ),
            denied_role_ids=_string_set(
                raw.get("denied_role_ids"), field_name="denied_role_ids"
            ),
            denied_department_ids=_string_set(
                raw.get("denied_department_ids"), field_name="denied_department_ids"
            ),
            denied_group_ids=_string_set(
                raw.get("denied_group_ids"), field_name="denied_group_ids"
            ),
            policy_revision=int(raw.get("policy_revision") or 1),
            schema_version=str(raw.get("schema_version") or "1.0"),
        )

    def allows(self, authz: Any) -> bool:
        subject_id = str(authz.subject_id)
        roles = {str(item).strip().lower() for item in authz.role_ids or ()}
        departments = {str(item) for item in authz.department_ids or ()}
        groups = {str(item) for item in authz.group_ids or ()}

        if (
            subject_id in self.denied_subject_ids
            or roles.intersection({item.lower() for item in self.denied_role_ids})
            or departments.intersection(self.denied_department_ids)
            or groups.intersection(self.denied_group_ids)
        ):
            return False
        if getattr(authz, "has_kb_admin", False):
            return True
        if self.owner_subject_id == subject_id:
            return True
        explicitly_allowed = bool(
            subject_id in self.allowed_subject_ids
            or roles.intersection({item.lower() for item in self.allowed_role_ids})
            or departments.intersection(self.allowed_department_ids)
            or groups.intersection(self.allowed_group_ids)
        )
        if self.visibility == "tenant":
            return True
        return explicitly_allowed

    def to_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema_version": self.schema_version,
                "policy_revision": self.policy_revision,
                "visibility": self.visibility,
                "owner_subject_id": self.owner_subject_id,
                "allowed_subject_ids": sorted(self.allowed_subject_ids),
                "allowed_role_ids": sorted(self.allowed_role_ids),
                "allowed_department_ids": sorted(self.allowed_department_ids),
                "allowed_group_ids": sorted(self.allowed_group_ids),
                "denied_subject_ids": sorted(self.denied_subject_ids),
                "denied_role_ids": sorted(self.denied_role_ids),
                "denied_department_ids": sorted(self.denied_department_ids),
                "denied_group_ids": sorted(self.denied_group_ids),
            }
        )
