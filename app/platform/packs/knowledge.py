"""Domain-neutral knowledge Pack contracts and fail-closed runtime.

Packs may contribute vocabulary and pure transformation rules.  They return
references only; the core remains the sole owner of tenant/ACL/revision,
authority, completeness, decision and citation admission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Protocol

from app.services.evidence_contract import EvidenceItem, ExecutionStatus


@dataclass(frozen=True)
class KnowledgeComponentContribution:
    component_key: str
    component_version: str
    component_path: str

    def __post_init__(self) -> None:
        if not self.component_key or not self.component_version:
            raise ValueError("knowledge component key and version are required")
        if ":" not in self.component_path:
            raise ValueError("knowledge component path must use module:attribute format")


@dataclass(frozen=True)
class KnowledgePackContribution:
    """Seven extension surfaces allowed to influence the canonical pipeline."""

    projectors: tuple[KnowledgeComponentContribution, ...] = ()
    requirement_compilers: tuple[KnowledgeComponentContribution, ...] = ()
    entity_alias_providers: tuple[KnowledgeComponentContribution, ...] = ()
    applicability_providers: tuple[KnowledgeComponentContribution, ...] = ()
    resolver_providers: tuple[KnowledgeComponentContribution, ...] = ()
    answer_renderers: tuple[KnowledgeComponentContribution, ...] = ()
    invariant_contributions: tuple[KnowledgeComponentContribution, ...] = ()

    def __post_init__(self) -> None:
        all_items: list[KnowledgeComponentContribution] = []
        for name in self.__dataclass_fields__:
            values = tuple(getattr(self, name) or ())
            object.__setattr__(self, name, values)
            all_items.extend(values)
        keys = [item.component_key for item in all_items]
        if len(keys) != len(set(keys)):
            raise ValueError("knowledge component keys must be unique within a Pack")

    @property
    def all_components(self) -> tuple[KnowledgeComponentContribution, ...]:
        return tuple(
            item
            for name in self.__dataclass_fields__
            for item in getattr(self, name)
        )


@dataclass(frozen=True)
class PackCandidate:
    """Untrusted Pack output; it intentionally contains no answer text."""

    pack_key: str
    tenant_id: str
    requirement_id: str
    unit_revision_id: str
    evidence_span_id: str
    source_revision_id: str
    artifact_id: str
    risk: str = "normal"
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required = (
            self.pack_key,
            self.tenant_id,
            self.requirement_id,
            self.unit_revision_id,
            self.evidence_span_id,
            self.source_revision_id,
            self.artifact_id,
        )
        if any(not str(value).strip() for value in required):
            raise ValueError("Pack candidate references must be complete")
        if self.risk not in {"normal", "high"}:
            raise ValueError("Pack candidate risk must be normal or high")
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))


class CoreAuthorityVerifier(Protocol):
    def __call__(self, candidate: PackCandidate) -> EvidenceItem | None: ...


@dataclass(frozen=True)
class PackAdmissionResult:
    evidence: tuple[EvidenceItem, ...]
    execution_status: ExecutionStatus
    reason_codes: tuple[str, ...] = ()


def admit_pack_candidates(
    candidates: Iterable[PackCandidate],
    *,
    tenant_id: str,
    active_pack_key: str,
    authority_verifier: CoreAuthorityVerifier,
) -> PackAdmissionResult:
    """Re-admit every Pack reference through core authority checks.

    A provider exception is execution failure, never evidence absence. High-risk
    manufacturing output requires a formally approved primary authority.
    """
    admitted: list[EvidenceItem] = []
    try:
        for candidate in candidates:
            if candidate.pack_key != active_pack_key:
                return PackAdmissionResult((), ExecutionStatus.SCHEMA_ERROR, ("pack.key_mismatch",))
            if candidate.tenant_id != tenant_id:
                return PackAdmissionResult((), ExecutionStatus.SCHEMA_ERROR, ("pack.cross_tenant_candidate",))
            evidence = authority_verifier(candidate)
            if evidence is None:
                continue
            if evidence.tenant_id != tenant_id:
                return PackAdmissionResult((), ExecutionStatus.SCHEMA_ERROR, ("core.cross_tenant_evidence",))
            if not (
                evidence.acl_verified
                and evidence.active_revision
                and evidence.release_active
                and evidence.quality_ready
                and not evidence.denied
                and not evidence.tombstoned
            ):
                continue
            if candidate.risk == "high" and evidence.authority_class not in {
                "formally_approved_sop",
                "formally_approved_primary",
            }:
                continue
            admitted.append(evidence)
    except Exception:
        return PackAdmissionResult((), ExecutionStatus.PACK_FAILURE, ("pack.execution_failure",))
    return PackAdmissionResult(tuple(admitted), ExecutionStatus.OK)


class KnowledgePackRuntime:
    """Atomic, tenant-scoped activation snapshot for knowledge contributions."""

    def __init__(self) -> None:
        self._installed: dict[str, tuple[str, KnowledgePackContribution]] = {}
        self._enabled: dict[str, frozenset[str]] = {}

    def install(self, pack_key: str, version: str, contribution: KnowledgePackContribution) -> None:
        if pack_key in self._installed:
            raise ValueError(f"knowledge Pack already installed: {pack_key}")
        self._installed = {**self._installed, pack_key: (version, contribution)}

    def enable(self, tenant_id: str, pack_key: str) -> None:
        if pack_key not in self._installed:
            raise KeyError(pack_key)
        self._enabled = {
            **self._enabled,
            tenant_id: frozenset((*self._enabled.get(tenant_id, frozenset()), pack_key)),
        }

    def disable(self, tenant_id: str, pack_key: str) -> None:
        self._enabled = {
            **self._enabled,
            tenant_id: frozenset(self._enabled.get(tenant_id, frozenset()) - {pack_key}),
        }

    def uninstall(self, pack_key: str) -> None:
        self._installed = {key: value for key, value in self._installed.items() if key != pack_key}
        self._enabled = {
            tenant: frozenset(keys - {pack_key}) for tenant, keys in self._enabled.items()
        }

    def active(self, tenant_id: str) -> tuple[tuple[str, str, KnowledgePackContribution], ...]:
        return tuple(
            (key, self._installed[key][0], self._installed[key][1])
            for key in sorted(self._enabled.get(tenant_id, frozenset()))
            if key in self._installed
        )

    def versions(self, tenant_id: str) -> dict[str, str]:
        return {key: version for key, version, _ in self.active(tenant_id)}

    def components(self, tenant_id: str) -> tuple[KnowledgeComponentContribution, ...]:
        return tuple(component for _, _, contribution in self.active(tenant_id) for component in contribution.all_components)

    def resolve_aliases(
        self,
        tenant_id: str,
        term: str,
        loader: Callable[[str], Callable[[str, str], Iterable[str]]],
    ) -> tuple[str, ...]:
        resolved: set[str] = set()
        try:
            for component in self.components(tenant_id):
                if ".alias." not in component.component_key:
                    continue
                resolved.update(str(value) for value in loader(component.component_path)(tenant_id, term))
        except Exception as exc:
            raise RuntimeError("knowledge Pack alias provider failed") from exc
        return tuple(sorted(resolved))
