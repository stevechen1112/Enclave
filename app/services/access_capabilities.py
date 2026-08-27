"""Server-owned role capability authority shared by API and runtime services."""

from __future__ import annotations

from typing import Any

ROLE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "owner": (
        "ask", "browse_knowledge", "upload_documents", "manage_sources",
        "review_queue", "governance", "system_ops", "create_content",
        "view_usage", "admin_home", "home",
    ),
    "admin": (
        "ask", "browse_knowledge", "upload_documents", "manage_sources",
        "review_queue", "governance", "system_ops", "create_content",
        "view_usage", "admin_home", "home",
    ),
    "hr": (
        "ask", "browse_knowledge", "upload_documents", "create_content",
        "view_usage", "home",
    ),
    "employee": (
        "ask", "browse_knowledge", "create_content", "view_usage", "home",
    ),
    "viewer": ("ask", "browse_knowledge", "view_usage", "home"),
}

SUPERUSER_CAPABILITIES = (
    "system_ops", "governance", "admin_home", "review_queue", "manage_sources",
)


def capabilities_for_user(user: Any) -> list[str]:
    role = str(getattr(user, "role", "") or "employee").lower()
    caps = list(ROLE_CAPABILITIES.get(role, ROLE_CAPABILITIES["employee"]))
    if bool(getattr(user, "is_superuser", False)):
        for capability in SUPERUSER_CAPABILITIES:
            if capability not in caps:
                caps.append(capability)
    return caps
