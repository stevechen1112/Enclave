"""Domain-neutral tenant application lifecycle contract."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


APPLICATION_LIFECYCLE_TRANSITIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "absent": frozenset({"installed"}),
        "installed": frozenset({"enabled", "archived"}),
        "enabled": frozenset({"disabled"}),
        "disabled": frozenset({"enabled", "archived"}),
        "archived": frozenset({"disabled", "removed"}),
        "removed": frozenset(),
    }
)

APPLICATION_LIFECYCLE_STATES = frozenset(APPLICATION_LIFECYCLE_TRANSITIONS)


def can_transition_application(from_state: str, to_state: str) -> bool:
    return to_state in APPLICATION_LIFECYCLE_TRANSITIONS.get(
        from_state, frozenset()
    )
