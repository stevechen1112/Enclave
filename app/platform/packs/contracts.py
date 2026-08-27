"""Versioned contracts for optional product packs.

The platform owns registration, dependency validation and deployment gating.
Packs own their domain implementation and tenant-specific eligibility query.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?$")
logger = logging.getLogger(__name__)


def _validate_key(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _KEY_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid {field_name}: {normalized!r}")
    return normalized


def _validate_version(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _VERSION_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid {field_name}: {normalized!r}")
    return normalized


@dataclass(frozen=True)
class PackDependency:
    pack_key: str
    minimum_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pack_key", _validate_key(self.pack_key, field_name="pack_key")
        )
        object.__setattr__(
            self,
            "minimum_version",
            _validate_version(self.minimum_version, field_name="minimum_version"),
        )


@dataclass(frozen=True)
class TaskHandlerContribution:
    handler_key: str
    handler_version: str
    task_name: str
    handler_path: str
    execution_boundary: str = "worker"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "handler_key",
            _validate_key(self.handler_key, field_name="handler_key"),
        )
        object.__setattr__(
            self,
            "handler_version",
            _validate_version(self.handler_version, field_name="handler_version"),
        )
        for field_name in ("task_name", "handler_path", "execution_boundary"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"{field_name} is required")


@dataclass(frozen=True)
class ProjectorContribution:
    projector_key: str
    projector_version: str
    source_kinds: tuple[str, ...]
    artifact_kinds: tuple[str, ...]
    projector_path: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "projector_key",
            _validate_key(self.projector_key, field_name="projector_key"),
        )
        object.__setattr__(
            self,
            "projector_version",
            _validate_version(self.projector_version, field_name="projector_version"),
        )
        object.__setattr__(self, "source_kinds", tuple(self.source_kinds or ()))
        object.__setattr__(self, "artifact_kinds", tuple(self.artifact_kinds or ()))
        if not self.source_kinds or not self.artifact_kinds:
            raise ValueError("projector source_kinds and artifact_kinds are required")
        if not str(self.projector_path or "").strip():
            raise ValueError("projector_path is required")


@dataclass(frozen=True)
class APIRouterContribution:
    router_key: str
    router_version: str
    router_path: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "router_key", _validate_key(self.router_key, field_name="router_key")
        )
        object.__setattr__(
            self,
            "router_version",
            _validate_version(self.router_version, field_name="router_version"),
        )
        if ":" not in str(self.router_path or ""):
            raise ValueError("router_path must use module:attribute format")


@dataclass(frozen=True)
class PermissionResolverContribution:
    resolver_key: str
    resolver_version: str
    resolver_path: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resolver_key",
            _validate_key(self.resolver_key, field_name="resolver_key"),
        )
        object.__setattr__(
            self,
            "resolver_version",
            _validate_version(self.resolver_version, field_name="resolver_version"),
        )
        if ":" not in str(self.resolver_path or ""):
            raise ValueError("resolver_path must use module:attribute format")


@dataclass(frozen=True)
class LifecycleHookContribution:
    hook_key: str
    hook_version: str
    event_key: str
    hook_path: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "hook_key", _validate_key(self.hook_key, field_name="hook_key")
        )
        object.__setattr__(
            self,
            "hook_version",
            _validate_version(self.hook_version, field_name="hook_version"),
        )
        _validate_key(self.event_key, field_name="event_key")
        if ":" not in str(self.hook_path or ""):
            raise ValueError("hook_path must use module:attribute format")


@dataclass(frozen=True)
class UIModuleContribution:
    ui_key: str
    ui_version: str
    route_keys: tuple[str, ...]
    module_key: str | None = None
    required_capability_keys: tuple[str, ...] = ()
    navigation: tuple[Mapping[str, str], ...] = ()
    bundle_key: str | None = None
    default_home: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ui_key", _validate_key(self.ui_key, field_name="ui_key")
        )
        if self.bundle_key is not None:
            object.__setattr__(
                self,
                "bundle_key",
                _validate_key(self.bundle_key, field_name="bundle_key"),
            )
        object.__setattr__(
            self,
            "ui_version",
            _validate_version(self.ui_version, field_name="ui_version"),
        )
        route_keys = tuple(self.route_keys or ())
        if not route_keys or len(route_keys) != len(set(route_keys)):
            raise ValueError("ui route_keys must be non-empty and unique")
        for route_key in route_keys:
            _validate_key(route_key, field_name="route_key")
        object.__setattr__(self, "route_keys", route_keys)
        if self.module_key is not None:
            object.__setattr__(
                self,
                "module_key",
                _validate_key(self.module_key, field_name="module_key"),
            )
        required = tuple(self.required_capability_keys or ())
        for capability in required:
            _validate_key(capability, field_name="required_capability_key")
        object.__setattr__(self, "required_capability_keys", required)
        object.__setattr__(
            self,
            "navigation",
            tuple(MappingProxyType(dict(item)) for item in (self.navigation or ())),
        )
        for item in self.navigation:
            if (
                not str(item.get("to") or "").startswith("/")
                or not str(item.get("label") or "").strip()
            ):
                raise ValueError("ui navigation requires an absolute path and label")
        if self.default_home is not None:
            default_home = str(self.default_home).strip()
            navigation_paths = {str(item.get("to")) for item in self.navigation}
            if not default_home.startswith("/") or default_home not in navigation_paths:
                raise ValueError("ui default_home must match a contributed navigation path")
            object.__setattr__(self, "default_home", default_home)


@dataclass(frozen=True)
class ReviewProviderContribution:
    """Optional pack adapter for the platform review workspace.

    The provider itself is loaded only after deployment and tenant entitlement
    checks pass, so the core API never imports an optional product domain.
    """

    provider_key: str
    provider_version: str
    provider_path: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_key",
            _validate_key(self.provider_key, field_name="provider_key"),
        )
        object.__setattr__(
            self,
            "provider_version",
            _validate_version(self.provider_version, field_name="provider_version"),
        )
        if ":" not in str(self.provider_path or ""):
            raise ValueError("provider_path must use module:attribute format")


@dataclass(frozen=True)
class PackManifest:
    pack_key: str
    pack_version: str
    display_name: str
    capability_keys: tuple[str, ...]
    module_keys: tuple[str, ...] = ()
    permission_keys: tuple[str, ...] = ()
    dependencies: tuple[PackDependency, ...] = ()
    tenant_binding_required: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pack_key", _validate_key(self.pack_key, field_name="pack_key")
        )
        object.__setattr__(
            self,
            "pack_version",
            _validate_version(self.pack_version, field_name="pack_version"),
        )
        if not str(self.display_name or "").strip():
            raise ValueError("display_name is required")
        for field_name in ("capability_keys", "module_keys", "permission_keys"):
            values = tuple(getattr(self, field_name) or ())
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {field_name} in pack {self.pack_key}")
            for value in values:
                _validate_key(value, field_name=field_name)
            object.__setattr__(self, field_name, values)
        if not self.capability_keys:
            raise ValueError("capability_keys is required")
        dependencies = tuple(self.dependencies or ())
        dependency_keys = [dependency.pack_key for dependency in dependencies]
        if len(dependency_keys) != len(set(dependency_keys)):
            raise ValueError(f"duplicate dependencies in pack {self.pack_key}")
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata or {}))
        )


@dataclass(frozen=True)
class PackTenantContext:
    tenant_id: UUID
    db: Any
    module_key: str | None = None


@runtime_checkable
class PackTenantEligibility(Protocol):
    def is_enabled(self, context: PackTenantContext) -> bool: ...


@dataclass(frozen=True)
class PackContribution:
    manifest: PackManifest
    knowledge_providers: tuple[Any, ...] = ()
    task_handlers: tuple[TaskHandlerContribution, ...] = ()
    projectors: tuple[ProjectorContribution, ...] = ()
    ui_modules: tuple[UIModuleContribution, ...] = ()
    api_routers: tuple[APIRouterContribution, ...] = ()
    permission_resolvers: tuple[PermissionResolverContribution, ...] = ()
    lifecycle_hooks: tuple[LifecycleHookContribution, ...] = ()
    review_providers: tuple[ReviewProviderContribution, ...] = ()
    tenant_eligibility: PackTenantEligibility | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "knowledge_providers",
            "task_handlers",
            "projectors",
            "ui_modules",
            "api_routers",
            "permission_resolvers",
            "lifecycle_hooks",
            "review_providers",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name) or ()))
        if self.manifest.tenant_binding_required and self.tenant_eligibility is None:
            raise ValueError(
                f"tenant eligibility is required for pack {self.manifest.pack_key}"
            )


class PackRegistry:
    """Deployment-scoped pack registry with deterministic contribution lookup."""

    def __init__(
        self,
        contributions: Iterable[PackContribution] = (),
        *,
        deployment_capabilities: Mapping[str, bool] | None = None,
    ) -> None:
        self._packs: dict[str, PackContribution] = {}
        self._sealed = False
        self._deployment_capabilities = dict(deployment_capabilities or {})
        for contribution in contributions:
            self.register(contribution)
        self.validate_dependencies()
        self._sealed = True

    def register(self, contribution: PackContribution) -> None:
        if self._sealed:
            raise RuntimeError("pack registry is immutable after composition")
        key = contribution.manifest.pack_key
        if key in self._packs:
            raise ValueError(f"duplicate pack_key: {key}")
        self._assert_unique_contribution_keys(contribution)
        self._packs[key] = contribution

    @property
    def pack_keys(self) -> tuple[str, ...]:
        return tuple(self._packs)

    @property
    def deployed_pack_keys(self) -> tuple[str, ...]:
        return tuple(key for key in self._packs if self.is_deployed(key))

    def get(self, pack_key: str) -> PackContribution | None:
        return self._packs.get(pack_key)

    def is_deployed(self, pack_key: str) -> bool:
        return pack_key in self._packs and self._deployment_capabilities.get(
            pack_key, True
        )

    def is_enabled_for_tenant(
        self,
        pack_key: str,
        *,
        context: PackTenantContext,
    ) -> bool:
        contribution = self._packs.get(pack_key)
        if contribution is None or not self.is_deployed(pack_key):
            return False
        eligibility = contribution.tenant_eligibility
        if eligibility is None:
            return True
        try:
            return bool(eligibility.is_enabled(context))
        except Exception:
            logger.exception("pack tenant eligibility failed closed: %s", pack_key)
            return False

    def knowledge_providers(self) -> tuple[Any, ...]:
        return tuple(
            provider
            for key, contribution in self._packs.items()
            if self.is_deployed(key)
            for provider in contribution.knowledge_providers
        )

    def task_handlers(self) -> tuple[TaskHandlerContribution, ...]:
        return tuple(
            handler
            for key, contribution in self._packs.items()
            if self.is_deployed(key)
            for handler in contribution.task_handlers
        )

    def projectors(self) -> tuple[ProjectorContribution, ...]:
        return tuple(
            projector
            for key, contribution in self._packs.items()
            if self.is_deployed(key)
            for projector in contribution.projectors
        )

    def permission_keys(self) -> tuple[str, ...]:
        return tuple(
            permission
            for key, contribution in self._packs.items()
            if self.is_deployed(key)
            for permission in contribution.manifest.permission_keys
        )

    def ui_modules(self) -> tuple[UIModuleContribution, ...]:
        return tuple(
            ui_module
            for key, contribution in self._packs.items()
            if self.is_deployed(key)
            for ui_module in contribution.ui_modules
        )

    def api_routers(self) -> tuple[APIRouterContribution, ...]:
        return tuple(
            router
            for key, contribution in self._packs.items()
            if self.is_deployed(key)
            for router in contribution.api_routers
        )

    def permission_resolvers(self) -> tuple[PermissionResolverContribution, ...]:
        return tuple(
            resolver
            for key, contribution in self._packs.items()
            if self.is_deployed(key)
            for resolver in contribution.permission_resolvers
        )

    def lifecycle_hooks(self) -> tuple[LifecycleHookContribution, ...]:
        return tuple(
            hook
            for key, contribution in self._packs.items()
            if self.is_deployed(key)
            for hook in contribution.lifecycle_hooks
        )

    def enabled_review_providers(
        self, *, context: PackTenantContext
    ) -> tuple[tuple[str, ReviewProviderContribution], ...]:
        enabled: list[tuple[str, ReviewProviderContribution]] = []
        for pack_key, contribution in self._packs.items():
            if not self.is_deployed(pack_key):
                continue
            if not self.is_enabled_for_tenant(pack_key, context=context):
                continue
            enabled.extend((pack_key, provider) for provider in contribution.review_providers)
        return tuple(enabled)

    def enabled_ui_modules(
        self, *, context: PackTenantContext
    ) -> tuple[tuple[str, UIModuleContribution], ...]:
        enabled: list[tuple[str, UIModuleContribution]] = []
        for pack_key, contribution in self._packs.items():
            if not self.is_deployed(pack_key):
                continue
            for ui_module in contribution.ui_modules:
                scoped_context = PackTenantContext(
                    tenant_id=context.tenant_id,
                    db=context.db,
                    module_key=ui_module.module_key,
                )
                if self.is_enabled_for_tenant(pack_key, context=scoped_context):
                    enabled.append((pack_key, ui_module))
        return tuple(enabled)

    def validate_dependencies(self) -> None:
        for contribution in self._packs.values():
            for dependency in contribution.manifest.dependencies:
                target = self._packs.get(dependency.pack_key)
                if target is None:
                    raise ValueError(
                        f"missing dependency {dependency.pack_key} for "
                        f"{contribution.manifest.pack_key}"
                    )
                if self.is_deployed(
                    contribution.manifest.pack_key
                ) and not self.is_deployed(dependency.pack_key):
                    raise ValueError(
                        f"disabled deployment dependency {dependency.pack_key} for "
                        f"{contribution.manifest.pack_key}"
                    )
                if self._version_tuple(
                    target.manifest.pack_version
                ) < self._version_tuple(dependency.minimum_version):
                    raise ValueError(
                        f"incompatible dependency {dependency.pack_key} for "
                        f"{contribution.manifest.pack_key}"
                    )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(pack_key: str) -> None:
            if pack_key in visiting:
                raise ValueError(f"circular pack dependency: {pack_key}")
            if pack_key in visited:
                return
            visiting.add(pack_key)
            for dependency in self._packs[pack_key].manifest.dependencies:
                visit(dependency.pack_key)
            visiting.remove(pack_key)
            visited.add(pack_key)

        for pack_key in self._packs:
            visit(pack_key)

    def _assert_unique_contribution_keys(self, contribution: PackContribution) -> None:
        existing_providers = {
            str(getattr(provider, "provider_key", ""))
            for pack in self._packs.values()
            for provider in pack.knowledge_providers
        }
        provider_keys = [
            str(getattr(provider, "provider_key", ""))
            for provider in contribution.knowledge_providers
        ]
        if any(not key for key in provider_keys) or len(provider_keys) != len(
            set(provider_keys)
        ):
            raise ValueError(
                "pack knowledge provider keys must be unique and non-empty"
            )
        if existing_providers.intersection(provider_keys):
            raise ValueError("duplicate knowledge provider key across packs")
        for provider in contribution.knowledge_providers:
            capabilities = tuple(getattr(provider, "capability_keys", ()) or ())
            if not capabilities or not set(capabilities).issubset(
                contribution.manifest.capability_keys
            ):
                raise ValueError(
                    "knowledge provider capabilities must be declared by pack"
                )
            if not str(getattr(provider, "provider_version", "") or "").strip():
                raise ValueError("knowledge provider version is required")
            if not callable(getattr(provider, "contribute", None)):
                raise TypeError("knowledge provider contribute() is required")

        existing_permissions = {
            permission
            for pack in self._packs.values()
            for permission in pack.manifest.permission_keys
        }
        if existing_permissions.intersection(contribution.manifest.permission_keys):
            raise ValueError("duplicate permission key across packs")

        for field_name, values, attr in (
            ("task handler", contribution.task_handlers, "handler_key"),
            ("projector", contribution.projectors, "projector_key"),
            ("ui module", contribution.ui_modules, "ui_key"),
            ("API router", contribution.api_routers, "router_key"),
            (
                "permission resolver",
                contribution.permission_resolvers,
                "resolver_key",
            ),
            ("lifecycle hook", contribution.lifecycle_hooks, "hook_key"),
            ("review provider", contribution.review_providers, "provider_key"),
        ):
            existing = {
                str(getattr(item, attr))
                for pack in self._packs.values()
                for item in getattr(pack, self._contribution_field(attr))
            }
            incoming = [str(getattr(item, attr)) for item in values]
            if len(incoming) != len(set(incoming)) or existing.intersection(incoming):
                raise ValueError(f"duplicate {field_name} key across packs")

        for ui_module in contribution.ui_modules:
            if (
                ui_module.module_key
                and ui_module.module_key not in contribution.manifest.module_keys
            ):
                raise ValueError("ui module_key must be declared by pack manifest")
            if not set(ui_module.required_capability_keys).issubset(
                contribution.manifest.capability_keys
            ):
                raise ValueError("ui capabilities must be declared by pack manifest")

        existing_routes = {
            route_key
            for pack in self._packs.values()
            for ui_module in pack.ui_modules
            for route_key in ui_module.route_keys
        }
        incoming_routes = [
            route_key
            for ui_module in contribution.ui_modules
            for route_key in ui_module.route_keys
        ]
        if len(incoming_routes) != len(
            set(incoming_routes)
        ) or existing_routes.intersection(incoming_routes):
            raise ValueError("duplicate ui route key across packs")

    @staticmethod
    def _contribution_field(attribute: str) -> str:
        return {
            "handler_key": "task_handlers",
            "projector_key": "projectors",
            "ui_key": "ui_modules",
            "router_key": "api_routers",
            "resolver_key": "permission_resolvers",
            "hook_key": "lifecycle_hooks",
            "provider_key": "review_providers",
        }[attribute]

    @staticmethod
    def _version_tuple(version: str) -> tuple[int, int, int]:
        return tuple(int(part) for part in version.split("-", 1)[0].split(".")[:3])
