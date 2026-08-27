"""MKA permission contribution independent from base role capabilities."""

from __future__ import annotations

from typing import Any

_ADMIN = {"owner", "admin"}


def resolve_permissions(user: Any) -> tuple[str, ...]:
    role = str(getattr(user, "role", "") or "").lower()
    permissions = {"mka.knowhow.read"}
    if role in {"owner", "admin", "hr", "employee"}:
        permissions.add("mka.knowhow.write")
    if role in _ADMIN or bool(getattr(user, "is_superuser", False)):
        permissions.update(("mka.approval.decide", "mka.module.admin"))
    return tuple(sorted(permissions))
