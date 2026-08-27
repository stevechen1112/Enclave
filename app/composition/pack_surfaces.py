"""Composition-only loader for deployed pack runtime surfaces."""

from __future__ import annotations

import importlib
from typing import Any

from fastapi import APIRouter

from app.platform.packs import PackRegistry


def load_contribution_object(path: str) -> Any:
    module_name, separator, attribute = str(path or "").partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("contribution path must use module:attribute format")
    module = importlib.import_module(module_name)
    return getattr(module, attribute)


def include_pack_routers(target: APIRouter, registry: PackRegistry) -> None:
    for contribution in registry.api_routers():
        router = load_contribution_object(contribution.router_path)
        if not isinstance(router, APIRouter):
            raise TypeError(f"pack router is not APIRouter: {contribution.router_key}")
        target.include_router(router)


def import_pack_task_modules(registry: PackRegistry) -> tuple[str, ...]:
    imported: list[str] = []
    for handler in registry.task_handlers():
        module_name, separator, _attribute = handler.handler_path.partition(":")
        if not separator:
            module_name = handler.handler_path.rpartition(".")[0]
        if not module_name:
            raise ValueError(f"invalid task handler path: {handler.handler_path}")
        importlib.import_module(module_name)
        if module_name not in imported:
            imported.append(module_name)
    return tuple(imported)


def resolve_pack_permissions(registry: PackRegistry, user: Any) -> tuple[str, ...]:
    permissions: set[str] = set()
    for contribution in registry.permission_resolvers():
        resolver = load_contribution_object(contribution.resolver_path)
        if not callable(resolver):
            raise TypeError(
                f"pack permission resolver is not callable: {contribution.resolver_key}"
            )
        permissions.update(str(item) for item in resolver(user) or ())
    return tuple(sorted(permissions))
