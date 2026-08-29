"""Deprecated import bridge for the training/know-how application.

New code imports app.packs.training_knowhow.persistence directly.
"""
from app.packs.training_knowhow.persistence import (
    MKAConflictError,
    MKAForbiddenError,
    MKANotFoundError,
    MKAPersistenceError,
    MKARepository,
    approval_to_dict,
    interaction_to_dict,
    knowhow_to_dict,
)

__all__ = [
    "MKAConflictError",
    "MKAForbiddenError",
    "MKANotFoundError",
    "MKAPersistenceError",
    "MKARepository",
    "approval_to_dict",
    "interaction_to_dict",
    "knowhow_to_dict",
]
