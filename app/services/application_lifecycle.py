"""Tenant-scoped application lifecycle orchestration.

The existing tenant_module_bindings table is retained as the entitlement
authority. Lifecycle metadata is stored in its versioned config envelope so
the transition can ship without a production schema migration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.composition.packs import build_pack_registry
from app.models.mka import TenantModuleBinding
from app.platform.packs import can_transition_application


class ApplicationLifecycleError(ValueError):
    pass


class ApplicationLifecycleService:
    METADATA_KEY = "_application_lifecycle"

    def __init__(self, db: Session):
        self.db = db
        self.registry = build_pack_registry()

    def _application(self, module_key: str):
        application = self.registry.application_for_module(module_key)
        if application is None:
            raise ApplicationLifecycleError(f"unknown application: {module_key}")
        return application

    def _binding(self, tenant_id: UUID, module_key: str):
        return (
            self.db.query(TenantModuleBinding)
            .filter(
                TenantModuleBinding.tenant_id == tenant_id,
                TenantModuleBinding.module_key == module_key,
            )
            .first()
        )

    def get_application(self, module_key: str):
        return self._application(module_key)

    def get_binding(self, tenant_id: UUID, module_key: str):
        self._application(module_key)
        return self._binding(tenant_id, module_key)

    def state(self, binding: TenantModuleBinding | None) -> str:
        if binding is None:
            return "absent"
        metadata = dict((binding.config_json or {}).get(self.METADATA_KEY) or {})
        explicit = str(metadata.get("state") or "")
        if explicit:
            return explicit
        return "enabled" if binding.enabled else "disabled"

    def _transition(
        self,
        *,
        tenant_id: UUID,
        module_key: str,
        to_state: str,
        actor_id: UUID | None,
        evidence: dict[str, Any] | None = None,
    ) -> TenantModuleBinding:
        application = self._application(module_key)
        binding = self._binding(tenant_id, module_key)
        from_state = self.state(binding)
        if not can_transition_application(from_state, to_state):
            raise ApplicationLifecycleError(
                f"invalid application transition: {from_state} -> {to_state}"
            )
        if binding is None:
            binding = TenantModuleBinding(
                tenant_id=tenant_id,
                module_key=module_key,
                module_version=application.application_version,
                enabled=False,
                license_state="suspended",
                config_json={},
            )
            self.db.add(binding)
        now = datetime.now(timezone.utc).isoformat()
        config = dict(binding.config_json or {})
        prior = dict(config.get(self.METADATA_KEY) or {})
        history = list(prior.get("history") or [])
        history.append(
            {
                "from": from_state,
                "to": to_state,
                "at": now,
                "actor_id": str(actor_id) if actor_id else None,
                "evidence": dict(evidence or {}),
            }
        )
        config[self.METADATA_KEY] = {
            **prior,
            "state": to_state,
            "application_key": application.application_key,
            "application_version": application.application_version,
            "changed_at": now,
            "history": history,
        }
        binding.config_json = config
        binding.config_version = int(binding.config_version or 0) + 1
        binding.enabled = to_state == "enabled"
        binding.license_state = "active" if to_state == "enabled" else (
            "expired" if to_state == "removed" else "suspended"
        )
        if to_state == "removed":
            binding.effective_to = datetime.now(timezone.utc)
        elif to_state == "enabled":
            binding.effective_to = None
        self.db.flush()
        return binding

    def install(self, tenant_id: UUID, module_key: str, *, actor_id: UUID | None = None):
        return self._transition(
            tenant_id=tenant_id,
            module_key=module_key,
            to_state="installed",
            actor_id=actor_id,
        )

    def enable(self, tenant_id: UUID, module_key: str, *, actor_id: UUID | None = None):
        return self._transition(
            tenant_id=tenant_id,
            module_key=module_key,
            to_state="enabled",
            actor_id=actor_id,
        )

    def disable(self, tenant_id: UUID, module_key: str, *, actor_id: UUID | None = None):
        return self._transition(
            tenant_id=tenant_id,
            module_key=module_key,
            to_state="disabled",
            actor_id=actor_id,
        )

    def archive(self, tenant_id: UUID, module_key: str, *, actor_id: UUID | None = None):
        return self._transition(
            tenant_id=tenant_id,
            module_key=module_key,
            to_state="archived",
            actor_id=actor_id,
        )

    def remove(
        self,
        tenant_id: UUID,
        module_key: str,
        *,
        actor_id: UUID | None = None,
        export_receipt: str | None = None,
        data_disposition: str,
        data_disposition_receipt: str | None = None,
    ):
        application = self._application(module_key)
        policy = application.data_policy
        if policy is None:
            raise ApplicationLifecycleError("application data policy missing")
        if policy.export_required_before_remove and not str(export_receipt or "").strip():
            raise ApplicationLifecycleError("export receipt is required before remove")
        allowed_disposition = (
            {"delete"}
            if policy.removal_behavior == "export_then_delete"
            else {"retain"}
        )
        if data_disposition not in allowed_disposition:
            raise ApplicationLifecycleError(
                f"data disposition must be one of {sorted(allowed_disposition)}"
            )
        if data_disposition == "delete" and not str(
            data_disposition_receipt or ""
        ).strip():
            raise ApplicationLifecycleError(
                "data disposition receipt is required after delete"
            )
        return self._transition(
            tenant_id=tenant_id,
            module_key=module_key,
            to_state="removed",
            actor_id=actor_id,
            evidence={
                "export_receipt": export_receipt,
                "data_disposition": data_disposition,
                "data_disposition_receipt": data_disposition_receipt,
                "policy": policy.removal_behavior,
            },
        )

    def set_enabled_compat(
        self,
        tenant_id: UUID,
        module_key: str,
        *,
        enabled: bool,
        actor_id: UUID | None = None,
    ) -> TenantModuleBinding:
        """Map the legacy boolean API onto the guarded lifecycle."""
        self._application(module_key)
        binding = self._binding(tenant_id, module_key)
        current = self.state(binding)
        if current in {"archived", "removed"}:
            raise ApplicationLifecycleError(
                f"application {current}; explicit lifecycle action is required"
            )
        if current == "absent":
            binding = self.install(tenant_id, module_key, actor_id=actor_id)
            current = "installed"
        if enabled and current in {"installed", "disabled"}:
            return self.enable(tenant_id, module_key, actor_id=actor_id)
        if not enabled and current == "enabled":
            return self.disable(tenant_id, module_key, actor_id=actor_id)
        assert binding is not None
        return binding
