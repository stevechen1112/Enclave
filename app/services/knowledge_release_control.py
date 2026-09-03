"""KQ7 signed two-stage tenant authorization and release identity controls."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.config import settings
from app.services.release_metadata import get_release_metadata

AUTH_SCHEMA_VERSION = "knowledge-decision-authorization/v1"
_LOCK = threading.Lock()
_UNKNOWN = {"", "unknown", "dev", "local", "unset"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
_ENFORCE_PREREQUISITES = frozenset(
    {
        "shadow_gate",
        "tenant_acceptance",
        "acl_negative",
        "rollback_drill",
        "browser_acceptance",
    }
)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class KnowledgeReleaseIdentity:
    backend_image_digest: str
    frontend_image_digest: str
    deployment_manifest_id: str
    kb_revision_id: str
    knowledge_release_id: str
    pack_versions: Mapping[str, str]
    prompt_version: str
    model_id: str
    rollback_point: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pack_versions", dict(sorted(dict(self.pack_versions).items()))
        )

    def errors(self) -> tuple[str, ...]:
        values = asdict(self)
        errors = [
            f"release_identity.{key}_missing"
            for key, value in values.items()
            if key != "pack_versions" and str(value).strip().casefold() in _UNKNOWN
        ]
        if not _IMAGE_DIGEST.fullmatch(self.backend_image_digest):
            errors.append("release_identity.backend_image_digest_invalid")
        if not _IMAGE_DIGEST.fullmatch(self.frontend_image_digest):
            errors.append("release_identity.frontend_image_digest_invalid")
        if not self.pack_versions:
            errors.append("release_identity.pack_versions_missing")
        return tuple(errors)

    @property
    def identity_hash(self) -> str:
        return hashlib.sha256(_canonical(asdict(self))).hexdigest()


def current_knowledge_release_identity() -> KnowledgeReleaseIdentity:
    release = get_release_metadata()
    try:
        packs = json.loads(
            str(getattr(settings, "KNOWLEDGE_DECISION_PACK_VERSIONS", "{}") or "{}")
        )
    except json.JSONDecodeError:
        packs = {}
    if not isinstance(packs, dict):
        packs = {}
    return KnowledgeReleaseIdentity(
        backend_image_digest=str(release.get("backend_image_digest") or ""),
        frontend_image_digest=str(release.get("frontend_image_digest") or ""),
        deployment_manifest_id=str(release.get("deployment_manifest_id") or ""),
        kb_revision_id=str(
            getattr(settings, "KNOWLEDGE_DECISION_KB_REVISION_ID", "") or ""
        ),
        knowledge_release_id=str(
            getattr(settings, "KNOWLEDGE_DECISION_RELEASE_ID", "") or ""
        ),
        pack_versions={str(k): str(v) for k, v in packs.items()},
        prompt_version=str(
            getattr(settings, "KNOWLEDGE_DECISION_PROMPT_VERSION", "") or ""
        ),
        model_id=str(getattr(settings, "OPENAI_MODEL", "") or ""),
        rollback_point=str(
            getattr(settings, "KNOWLEDGE_DECISION_ROLLBACK_POINT", "") or ""
        ),
    )


@dataclass(frozen=True)
class TenantDecisionAuthorization:
    authorization_id: str
    tenant_id: str
    mode: str
    scope: tuple[str, ...]
    traffic_percent: int
    not_before: str
    expires_at: str
    release_identity: Mapping[str, Any]
    release_identity_hash: str
    data_use_scope: tuple[str, ...]
    rollback_owner: str
    stop_conditions: tuple[str, ...]
    owner_id: str
    issued_at: str
    prerequisite_evidence: Mapping[str, str] = field(default_factory=dict)
    supersedes_authorization_id: str | None = None
    schema_version: str = AUTH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", tuple(self.scope))
        object.__setattr__(self, "data_use_scope", tuple(self.data_use_scope))
        object.__setattr__(self, "stop_conditions", tuple(self.stop_conditions))
        object.__setattr__(self, "release_identity", dict(self.release_identity))
        object.__setattr__(
            self, "prerequisite_evidence", dict(self.prerequisite_evidence)
        )

    def validation_errors(
        self,
        *,
        tenant_id: str,
        requested_mode: str,
        release_identity: KnowledgeReleaseIdentity,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        errors: list[str] = []
        point = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if self.schema_version != AUTH_SCHEMA_VERSION:
            errors.append("authorization.schema_version_invalid")
        if self.tenant_id != tenant_id:
            errors.append("authorization.tenant_mismatch")
        if self.mode != requested_mode or self.mode not in {"shadow", "enforce"}:
            errors.append("authorization.mode_mismatch")
        if not (1 <= int(self.traffic_percent) <= 100):
            errors.append("authorization.traffic_invalid")
        try:
            if point < _parse_time(self.not_before) or point >= _parse_time(
                self.expires_at
            ):
                errors.append("authorization.outside_time_window")
        except ValueError:
            errors.append("authorization.time_invalid")
        if (
            "ask" not in self.scope
            or not self.data_use_scope
            or not self.rollback_owner
            or not self.owner_id
        ):
            errors.append("authorization.required_scope_or_owner_missing")
        if not self.stop_conditions:
            errors.append("authorization.stop_conditions_missing")
        if release_identity.errors():
            errors.extend(release_identity.errors())
        expected_release = asdict(release_identity)
        if (
            self.release_identity_hash != release_identity.identity_hash
            or dict(self.release_identity) != expected_release
        ):
            errors.append("authorization.release_identity_mismatch")
        if requested_mode == "enforce":
            missing = _ENFORCE_PREREQUISITES - set(self.prerequisite_evidence)
            if missing:
                errors.append(
                    "authorization.enforce_prerequisites_missing:"
                    + ",".join(sorted(missing))
                )
            if any(
                not re.fullmatch(r"[0-9a-fA-F]{64}", str(value or ""))
                for key, value in self.prerequisite_evidence.items()
                if key in _ENFORCE_PREREQUISITES
            ):
                errors.append("authorization.enforce_evidence_digest_invalid")
        return tuple(errors)

    def unsigned_payload(self) -> dict[str, Any]:
        return asdict(self)


def sign_authorization(record: TenantDecisionAuthorization, key: str) -> str:
    if not key:
        raise ValueError("authorization signing key is required")
    return hmac.new(
        key.encode("utf-8"), _canonical(record.unsigned_payload()), hashlib.sha256
    ).hexdigest()


class AuthorizationStore:
    """Append-only signed authorization records with an audit digest chain."""

    def __init__(self, root: str | Path, *, key: str):
        self.root = Path(root).resolve()
        self.key = key

    def append(
        self, record: TenantDecisionAuthorization, *, signature: str | None = None
    ) -> Path:
        if not _SAFE_ID.fullmatch(record.authorization_id):
            raise ValueError("authorization_id contains unsafe characters")
        if record.mode not in {"shadow", "enforce"}:
            raise ValueError("authorization mode must be shadow or enforce")
        signature = signature or sign_authorization(record, self.key)
        payload = {"record": record.unsigned_payload(), "signature": signature}
        path = self.root / f"{record.authorization_id}.json"
        self.root.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            audit_path = self.root / "authorization-audit.jsonl"
            previous_hash = "0" * 64
            if audit_path.exists():
                rows = audit_path.read_text(encoding="utf-8").splitlines()
                if rows:
                    previous_hash = str(json.loads(rows[-1]).get("event_hash") or "")
            event = {
                "event": "authorization_appended",
                "authorization_id": record.authorization_id,
                "mode": record.mode,
                "tenant_ref": hashlib.sha256(record.tenant_id.encode()).hexdigest()[
                    :24
                ],
                "record_sha256": digest,
                "previous_event_hash": previous_hash,
            }
            event["event_hash"] = hmac.new(
                self.key.encode("utf-8"), _canonical(event), hashlib.sha256
            ).hexdigest()
            with audit_path.open("a", encoding="utf-8") as audit:
                audit.write(json.dumps(event, sort_keys=True) + "\n")
                audit.flush()
                os.fsync(audit.fileno())
        return path

    def active_authorization(
        self,
        *,
        tenant_id: str,
        requested_mode: str,
        release_identity: KnowledgeReleaseIdentity,
        now: datetime | None = None,
    ) -> TenantDecisionAuthorization | None:
        if not self.key or not self.root.exists():
            return None
        matches: list[TenantDecisionAuthorization] = []
        for path in self.root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                record = TenantDecisionAuthorization(**payload["record"])
                expected = sign_authorization(record, self.key)
                if not hmac.compare_digest(
                    str(payload.get("signature") or ""), expected
                ):
                    continue
                if not record.validation_errors(
                    tenant_id=tenant_id,
                    requested_mode=requested_mode,
                    release_identity=release_identity,
                    now=now,
                ):
                    matches.append(record)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return max(matches, key=lambda item: _parse_time(item.issued_at), default=None)


def authorization_for_requested_mode(
    tenant_id: str, mode: str
) -> TenantDecisionAuthorization | None:
    if mode not in {"shadow", "enforce"}:
        return None
    store = AuthorizationStore(
        getattr(
            settings,
            "KNOWLEDGE_DECISION_AUTHORIZATION_STORE_PATH",
            "artifacts/knowledge/authorizations",
        ),
        key=str(getattr(settings, "KNOWLEDGE_DECISION_AUTHORIZATION_KEY", "") or ""),
    )
    return store.active_authorization(
        tenant_id=tenant_id,
        requested_mode=mode,
        release_identity=current_knowledge_release_identity(),
    )


def request_is_in_authorized_traffic(
    authorization: TenantDecisionAuthorization, request_id: str | None
) -> bool:
    if authorization.traffic_percent >= 100:
        return True
    if not request_id:
        return False
    bucket = (
        int(
            hashlib.sha256(
                f"{authorization.tenant_id}:{request_id}".encode("utf-8")
            ).hexdigest()[:8],
            16,
        )
        % 100
    )
    return bucket < authorization.traffic_percent


def requested_mode_is_authorized(
    tenant_id: str, mode: str, *, request_id: str | None = None
) -> bool:
    authorization = authorization_for_requested_mode(tenant_id, mode)
    return authorization is not None and request_is_in_authorized_traffic(
        authorization, request_id
    )
